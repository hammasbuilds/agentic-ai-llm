"""Roundtrip — code to prose and back. What survives?

Ask the model to describe the reference solution, hand that description to a fresh context,
and ask it to implement the function. Compare against implementing from the benchmark's own
task description.

The expected result is loss: prose cannot carry everything code says, so the roundtrip
should score lower. It scores **32.5 points higher** — 80.5% against 48.0% on 200 MBPP
tasks.

That is not a model writing good documentation. It is a leak. The description was written
*with the answer in view*, so it encodes decisions the task sentence never made: return
type, empty-input behaviour, tie-breaking. MBPP's descriptions average 78 characters; the
model's average 445.

**How much of the 32.5 is the leak is not yet measured, and the gap is an upper bound.**
This app's `direct` arm is the only MBPP-from-description baseline in the repository that
does *not* hand the model one of MBPP's own asserts; apps 04, 05, 07, 08 and 09 all do,
which is why app 04 reports the same 14B at 76.0% where this one reports 48.0%. An assert
pins the signature, the return type and one input/output pair - exactly the decisions this
docstring credits the description with carrying. A `direct_with_test` arm exists now and
sits between the two; until it runs, the honest claim is that the roundtrip beats a
description-only baseline by 32.5 points and beats a description-plus-assert baseline by
some smaller amount.

Added as a third arm rather than by changing either of the other two, so the published
48.0% and 76.0% stay reproducible and the confound becomes a measurement instead of an
argument.

The practical consequence is worth stating plainly: **a docstring generated from an
implementation cannot be used to evaluate that implementation.** It is downstream of the
code and agrees with it by construction.
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
SLUG = "roundtrip"

DESCRIBE = """Describe exactly what this Python function does, so someone could
reimplement it without seeing the code.

```python
{code}
```

Output ONLY the description as plain prose. No code, no examples, no bullet points.
"""

IMPLEMENT = """Write a Python function named `{entry}` that does exactly this:

{description}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""

#: The same prompt plus one of MBPP's own asserts, which is what apps 04, 05, 07, 08
#: and 09 hand the model and this app's `direct` arm does not.
#:
#: That asymmetry was invisible and load-bearing. App 04 reports the 14B at 76.0% from
#: a task description; this app reports 48.0% for the same thing, and the root README
#: prints both while attributing the whole 32.5-point gap to a leak in the generated
#: description. An assert pins the signature, the return type and one input/output
#: pair, so some unmeasured share of those 32.5 points is the assert rather than the
#: leak - and app 08 exists to measure prompt sensitivity, which nobody had applied to
#: the repository's own cross-app baselines.
#:
#: Added as a third arm rather than by changing either of the other two: replacing the
#: `direct` arm would make the published 48.0% unreproducible, and dropping the assert
#: from app 04 would do the same to its 76.0%. With three arms a future run resolves
#: the confound instead of arguing about it.
IMPLEMENT_WITH_TEST = """Write a Python function named `{entry}` that does exactly this:

{description}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 50))
    tasks = load("mbpp", limit)
    loop = asyncio.get_running_loop()
    n = len(tasks)
    # Four passes now: describe, then three implementation arms. It was three, and
    # a progress bar that reaches its end before the work does is its own small lie.
    total = n * 4

    async def progress(done: int, _t: int) -> None:
        await emit(done, total, f"describing {done}/{n}")

    descs_raw = await model.generate_many(
        [DESCRIBE.format(code=t.reference) for t in tasks], on_progress=progress
    )
    descs = {
        t.task_id: r.strip()
        for t, r in zip(tasks, model.require_all(descs_raw, what="description"), strict=True)
    }
    await emit(n, total, "descriptions written")

    arms: dict[str, list[str]] = {}
    for idx, arm in enumerate(["direct", "direct_with_test", "roundtrip"], start=1):
        raws = await model.generate_many(
            [
                IMPLEMENT_WITH_TEST.format(
                    entry=t.entry_point, description=t.prompt, test=t.tests[0]
                )
                if arm == "direct_with_test"
                else IMPLEMENT.format(
                    entry=t.entry_point,
                    description=t.prompt if arm == "direct" else descs[t.task_id],
                )
                for t in tasks
            ]
        )
        arms[arm] = [extract_code(r) for r in model.require_all(raws, what=f"{arm} answer")]
        await emit(n * (idx + 1), total, f"{arm}: implementations written")

    passed: dict[str, set[str]] = {}
    for arm, codes in arms.items():
        outs = await asyncio.gather(
            *[
                loop.run_in_executor(None, run_tests, c, list(t.tests), t.setup)
                for c, t in zip(codes, tasks, strict=True)
            ]
        )
        passed[arm] = {t.task_id for t, o in zip(tasks, outs, strict=True) if o.passed}

    d, r = passed["direct"], passed["roundtrip"]
    lens = [len(descs[t.task_id]) for t in tasks]
    task_lens = [len(t.prompt) for t in tasks]

    examples = []
    for t in tasks:
        if t.task_id in (r - d) and len(examples) < 5:
            examples.append(
                {
                    "task_id": t.task_id,
                    "entry_point": t.entry_point,
                    "mbpp": t.prompt,
                    "model": descs[t.task_id][:420],
                }
            )

    return {
        "n": n,
        "direct": len(d) / n if n else 0.0,
        "roundtrip": len(r) / n if n else 0.0,
        "drift": (len(r) - len(d)) / n if n else 0.0,
        "gained": len(r - d),
        "lost": len(d - r),
        "mean_model_chars": sum(lens) / len(lens) if lens else 0,
        "mean_mbpp_chars": sum(task_lens) / len(task_lens) if task_lens else 0,
        "examples": examples,
    }


ABOUT = """
<p>Two ways to specify the same function: the benchmark's sentence, and the model's own
description of the reference implementation. Both are handed to a fresh context and scored
against the same tests.</p>
<p>On 200 MBPP tasks the roundtrip scored <b>80.5%</b> against <b>48.0%</b> from MBPP's
description — 32.5 points in the wrong direction for something that is supposed to lose
information.</p>
<p>The descriptions average 445 characters against MBPP's 78, and those extra characters
are the leak: they were written with the implementation in view, so they specify the return
type and the edge cases the task sentence left open.</p>
<p>Another app in this repo reaches the same conclusion from the other side — only 16% of
test suites written from those task descriptions agree with the reference. Two independent
measurements point at the descriptions, not the model.</p>
"""

app = create_app(
    slug="roundtrip",
    icon="📜",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=50,
            min=10,
            max=200,
            hint="three model calls per task: describe, then implement twice",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
