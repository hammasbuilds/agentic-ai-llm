"""Repair or Rewrite — given failing code, patch it or throw it away?

Agents almost always patch. Shown a failure, they send the broken code back with the error
and ask for a fix. The alternative — discard it and regenerate from the task — is rarely
tried and almost never compared, even though the two have different costs and different
failure modes. Repair sends the broken code back in the prompt, so it costs more tokens
*and* anchors the model on an approach that already failed.

Both arms start from the same failed attempt and get exactly one more call, so the
comparison is like for like.

Measured on 250 MBPP tasks with 60 first-attempt failures: repair fixed 1, rewrite fixed 3,
and **56 survived both**. The gap between 1 and 3 out of 60 is noise, not a result — the
finding is the 93.3%. Tasks a model fails first time are mostly tasks it cannot do.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.datasets import load  # noqa: E402
from apps._engine.execute import extract_code  # noqa: E402
from apps._engine.execute import run as run_tests  # noqa: E402
from apps._platform import model  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "repair-rewrite"

FIRST = """Write a Python function for this task.

Task: {prompt}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""

REPAIR = """This Python function is wrong.

Task: {prompt}

Your code:
```python
{code}
```

Running the tests gave:
{error}

Fix it. Output ONLY the corrected function and any imports it needs. No explanation.
"""

REWRITE = """Write a Python function for this task.

Task: {prompt}

It must satisfy this test:
{test}

A previous attempt failed. Take a different approach.
Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 80))
    tasks = load("mbpp", limit)
    loop = asyncio.get_running_loop()

    async def progress(done: int, total: int) -> None:
        await emit(done, total * 2, f"first attempt {done}/{total}")

    raws = await model.generate_many(
        [FIRST.format(prompt=t.prompt, test=t.tests[0]) for t in tasks],
        on_progress=progress,
    )
    codes = [extract_code(r) for r in model.require_all(raws, what="first attempt")]
    outs = await asyncio.gather(
        *[
            loop.run_in_executor(None, run_tests, c, list(t.tests), t.setup)
            for c, t in zip(codes, tasks, strict=True)
        ]
    )
    failed = [(t, c, o.detail) for t, c, o in zip(tasks, codes, outs, strict=True) if not o.passed]
    first_pass = (len(tasks) - len(failed)) / len(tasks) if tasks else 0.0
    await emit(
        len(tasks),
        len(tasks) * 2,
        f"first-attempt pass@1 {first_pass:.1%} — {len(failed)} failures to work with",
    )

    if not failed:
        return {
            "n": len(tasks),
            "first_pass": first_pass,
            "failures": 0,
            "repair": 0,
            "rewrite": 0,
            "both": 0,
            "neither": 0,
            "examples": [],
        }

    # Different seeds so the two arms are genuinely two attempts, not one decode twice.
    rp = await model.generate_many(
        [
            REPAIR.format(prompt=t.prompt, code=c, error=e or "the tests failed")
            for t, c, e in failed
        ],
        seeds=[1] * len(failed),
    )
    rw = await model.generate_many(
        [REWRITE.format(prompt=t.prompt, test=t.tests[0]) for t, _, _ in failed],
        seeds=[2] * len(failed),
    )
    await emit(len(tasks) * 2, len(tasks) * 2, "scoring both retry arms")

    # Both arms, before either is scored: a lost generation in one arm would otherwise
    # be counted as that arm failing, and the whole point here is which arm wins.
    repaired = model.require_all(rp, what="repair")
    rewritten = model.require_all(rw, what="rewrite")

    rp_out = await asyncio.gather(
        *[
            loop.run_in_executor(None, run_tests, extract_code(r), list(t.tests), t.setup)
            for (t, _, _), r in zip(failed, repaired, strict=True)
        ]
    )
    rw_out = await asyncio.gather(
        *[
            loop.run_in_executor(None, run_tests, extract_code(r), list(t.tests), t.setup)
            for (t, _, _), r in zip(failed, rewritten, strict=True)
        ]
    )

    counts = {"repair": 0, "rewrite": 0, "both": 0, "neither": 0}
    examples = []
    for (task, _, err), ro, wo in zip(failed, rp_out, rw_out, strict=True):
        r_ok, w_ok = ro.passed, wo.passed
        counts["repair"] += r_ok
        counts["rewrite"] += w_ok
        if r_ok and w_ok:
            counts["both"] += 1
        elif not r_ok and not w_ok:
            counts["neither"] += 1
        if len(examples) < 8:
            examples.append(
                {
                    "task_id": task.task_id,
                    "repair": r_ok,
                    "rewrite": w_ok,
                    "error": (err or "")[:70],
                }
            )

    f = len(failed)
    return {
        "n": len(tasks),
        "first_pass": first_pass,
        "failures": f,
        "repair": counts["repair"],
        "rewrite": counts["rewrite"],
        "both": counts["both"],
        "neither": counts["neither"],
        "only_repair": counts["repair"] - counts["both"],
        "only_rewrite": counts["rewrite"] - counts["both"],
        "repair_rate": counts["repair"] / f,
        "rewrite_rate": counts["rewrite"] / f,
        "neither_rate": counts["neither"] / f,
        "examples": examples,
    }


ABOUT = """
<p>One failed attempt, two ways to spend one more call. Same failure, same budget.</p>
<p>On 250 MBPP tasks with 60 first-attempt failures: repair fixed 1, rewrite fixed 3,
<b>56 survived both</b>. This app deliberately does not report "rewrite beats repair" — 1
against 3 out of 60 is two numbers inside the noise, and dressing that up as a result would
be wrong.</p>
<p>The finding is the 93.3%, and it matches the self-debug ceiling measured elsewhere in
this repo from the other direction: rounds 3 to 5 of a feedback loop added zero tasks.
First-attempt failures are mostly things the model cannot do, not things it is one nudge
away from — which is worth knowing before building an agent around a retry loop.</p>
"""

app = create_app(
    slug="repair-rewrite",
    icon="🔀",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=80,
            min=10,
            max=300,
            hint="first attempt on all of them, then two retries per failure",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
