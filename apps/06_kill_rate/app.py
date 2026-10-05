"""Kill Rate — do model-written tests catch anything?

"Write tests for this" is one of the most common things anyone asks a coder model, and the
usual way to judge the answer is coverage. Coverage is a bad judge: a test that calls every
line and asserts nothing scores 100%.

So score them the way mutation testing does. Break the reference solution in one place and
ask whether the generated tests notice.

Two arms, because the first version of this failed in a way worth keeping:

- **from_description** — the model sees only the task sentence, as someone working from a
  ticket would. Almost none of these suites pass the reference. Not because the tests are
  bad: the sentence never says whether the function returns a list or a tuple, so the model
  guesses. This arm's validity rate measures the *spec*.
- **from_code** — the model sees the implementation, as someone adding tests to existing
  code would. These are valid, and their kill rate is the number this is about.

Measured on 150 tasks: 16.0% of description-written suites agree with the reference against
40.7% of code-written ones, and on the valid suites the model kills **93.4%** of mutants
against MBPP's own **85.0%**, with 3.7x as many asserts.
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.datasets import load  # noqa: E402
from apps._engine.execute import extract_code  # noqa: E402
from apps._engine.execute import run as run_tests  # noqa: E402
from apps._engine.mutate import mutants  # noqa: E402
from apps._platform import model  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "kill-rate"

FROM_DESCRIPTION = """Write assert statements that test this Python function thoroughly.

Task: {prompt}

The function is called `{entry}`.

Rules:
- Output ONLY assert statements, one per line.
- Cover edge cases: empty input, boundaries, zero, negatives, single elements.
- Do not redefine the function. Do not import anything. No explanation.
"""

FROM_CODE = """Write assert statements that test this Python function thoroughly.

```python
{code}
```

Rules:
- Output ONLY assert statements, one per line, calling `{entry}`.
- The assertions must match what this code actually does.
- Cover edge cases: empty input, boundaries, zero, negatives, single elements.
- Do not redefine the function. Do not import anything. No explanation.
"""

ARMS = {"from_description": FROM_DESCRIPTION, "from_code": FROM_CODE}
_ASSERT = re.compile(r"^\s*assert\s+")


def parse_asserts(raw: str, limit: int = 20) -> list[str]:
    """Keep the assert lines that are individually valid Python.

    The last assert is routinely truncated by the token limit - `assert f([1,` - and one
    unclosed bracket makes the whole suite a SyntaxError, which would be scored as "this
    suite rejects the reference" and drop the task from the sample.
    """
    out: list[str] = []
    for line in extract_code(raw).splitlines():
        line = line.strip()
        if not _ASSERT.match(line) or line in out:
            continue
        try:
            ast.parse(line)
        except SyntaxError:
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return out


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 40))
    per_problem = int(params.get("per_problem", 8))
    tasks = [t for t in load("mbpp", limit) if t.entry_point]
    loop = asyncio.get_running_loop()

    summary: dict[str, dict] = {}
    examples: list[dict] = []
    total_steps = 2 * len(tasks)
    step = 0

    for arm, template in ARMS.items():
        raws = await model.generate_many(
            [
                template.format(prompt=t.prompt, entry=t.entry_point, code=t.reference)
                for t in tasks
            ],
        )
        suites = {
            t.task_id: parse_asserts(r)
            for t, r in zip(tasks, model.require_all(raws, what=f"{arm} suite"), strict=True)
        }
        step += len(tasks)
        await emit(step, total_steps, f"{arm}: {len(tasks)} suites generated")

        checks = await asyncio.gather(
            *[
                loop.run_in_executor(None, run_tests, t.reference, suites[t.task_id], t.setup)
                for t in tasks
            ]
        )
        valid = [t for t, o in zip(tasks, checks, strict=True) if o.passed and suites[t.task_id]]

        run = killed_model = killed_bench = 0
        for t in valid:
            muts = mutants(t.reference, limit=per_problem)
            if not muts:
                continue
            mo = await asyncio.gather(
                *[
                    loop.run_in_executor(None, run_tests, m.code, suites[t.task_id], t.setup)
                    for m in muts
                ]
            )
            bo = await asyncio.gather(
                *[
                    loop.run_in_executor(None, run_tests, m.code, list(t.tests), t.setup)
                    for m in muts
                ]
            )
            run += len(muts)
            killed_model += sum(1 for o in mo if not o.passed)
            killed_bench += sum(1 for o in bo if not o.passed)
            if arm == "from_code" and len(examples) < 6 and suites[t.task_id]:
                examples.append(
                    {
                        "task_id": t.task_id,
                        "entry_point": t.entry_point,
                        "model_asserts": suites[t.task_id][:6],
                        "mbpp_asserts": list(t.tests)[:3],
                    }
                )

        summary[arm] = {
            "suites": len(tasks),
            "valid": len(valid),
            "validity": len(valid) / len(tasks) if tasks else 0.0,
            "mutants": run,
            "kill_rate": killed_model / run if run else 0.0,
            "bench_kill_rate": killed_bench / run if run else 0.0,
            "mean_asserts": (sum(len(suites[t.task_id]) for t in valid) / len(valid))
            if valid
            else 0.0,
        }
        step += len(tasks) * 0
        await emit(step, total_steps, f"{arm}: {len(valid)} valid suites, {run} mutants scored")

    fc = summary.get("from_code", {})
    return {
        "n": len(tasks),
        "arms": summary,
        "examples": examples,
        "advantage": fc.get("kill_rate", 0.0) - fc.get("bench_kill_rate", 0.0),
        "assert_ratio": (fc.get("mean_asserts", 0.0) / 3.0) if fc else 0.0,
    }


ABOUT = """
<p>Generated tests scored by mutation kill rate, not coverage — because a test that calls
every line and asserts nothing has perfect coverage and catches nothing.</p>
<p>On 150 MBPP tasks, suites written <b>from the implementation</b> kill <b>93.4%</b> of
mutants against MBPP's own <b>85.0%</b>, using 3.7x as many asserts. Generated tests beat
the benchmark's own, which says as much about three-assert benchmarks as about the model.</p>
<p>Suites written <b>from the task description</b> are a different story: only 16.0% even
agree with the reference. The descriptions do not say whether a function returns a list or
a tuple, or what empty input does, so the model guesses and guesses differently. That
number measures the spec, not the model — and a second app here reaches the same conclusion
from the opposite direction.</p>
"""

app = create_app(
    slug="kill-rate",
    icon="🎯",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=40,
            min=5,
            max=200,
            hint="each task gets two generated suites and many mutant executions",
        ),
        Field("per_problem", "Mutants per task", default=8, min=1, max=16),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
