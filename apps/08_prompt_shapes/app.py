"""Prompt Shapes — how much of a benchmark score is the wording?

Same model, same temperature, same tasks, same execution rule. The only thing that changes
is how the task is phrased. Whatever spread appears is attributable to formatting alone, and
it is a floor on how much of any published pass@1 is a property of the harness rather than
of the model.

Five shapes carrying identical information: the task as MBPP writes it, the same text inside
a docstring, the same text as a comment, a signature to complete, and the bare minimum.

The sharper number than the spread is the **flip count**: how many tasks are solved under
one phrasing and not another. A task that flips was never a measurement of capability.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.datasets import load  # noqa: E402
from apps._engine.execute import extract_code  # noqa: E402
from apps._engine.execute import run as run_tests  # noqa: E402
from apps._platform import model  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "prompt-shapes"

SHAPES = {
    "plain": (
        "Write a Python function for this task.\n\nTask: {prompt}\n\n"
        "It must satisfy this test:\n{test}\n\n"
        "Output ONLY the function definition and any imports it needs."
    ),
    "docstring": (
        "Complete this Python function.\n\n"
        'def {entry}(...):\n    """{prompt}\n\n    >>> {test_expr}\n    """\n\n'
        "Output ONLY the complete function including its signature."
    ),
    "comment": (
        "# {prompt}\n# Must satisfy: {test}\n\nWrite the Python function. Output ONLY the code."
    ),
    "signature": (
        "Implement `{entry}`.\n\n{prompt}\n\nExample: {test}\n\n"
        "Output ONLY the function definition."
    ),
    "terse": "{prompt}\n{test}",
}


def build(shape: str, task) -> str:
    test = task.tests[0]
    return SHAPES[shape].format(
        prompt=task.prompt,
        test=test,
        entry=task.entry_point,
        test_expr=test.replace("assert ", "").strip(),
    )


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 60))
    tasks = load("mbpp", limit)
    loop = asyncio.get_running_loop()
    n = len(tasks)
    total = n * len(SHAPES)
    step = 0

    scores: dict[str, float] = {}
    solved: dict[str, set[str]] = {}

    for shape in SHAPES:
        raws = await model.generate_many([build(shape, t) for t in tasks])
        codes = [extract_code(r) for r in model.require_all(raws, what=f"{shape} answer")]
        outs = await asyncio.gather(
            *[
                loop.run_in_executor(None, run_tests, c, list(t.tests), t.setup)
                for c, t in zip(codes, tasks, strict=True)
            ]
        )
        ok = {t.task_id for t, o in zip(tasks, outs, strict=True) if o.passed}
        solved[shape] = ok
        scores[shape] = len(ok) / n if n else 0.0
        step += n
        await emit(step, total, f"{shape}: pass@1 {scores[shape]:.1%}")

    vals = list(scores.values())
    union = set().union(*solved.values()) if solved else set()
    inter = set.intersection(*solved.values()) if solved else set()
    flipped = sorted(union - inter)

    # Which shape is the lone solver for a flipped task - useful for seeing whether one
    # phrasing is carrying the others or whether it is scattered.
    lone: dict[str, int] = {s: 0 for s in SHAPES}
    for tid in flipped:
        owners = [s for s in SHAPES if tid in solved[s]]
        if len(owners) == 1:
            lone[owners[0]] += 1

    return {
        "n": n,
        "scores": scores,
        "spread": max(vals) - min(vals) if vals else 0.0,
        "stdev": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
        "best": max(scores, key=scores.get) if scores else "",
        "worst": min(scores, key=scores.get) if scores else "",
        "solved_by_any": len(union),
        "solved_by_all": len(inter),
        "flipped": len(flipped),
        "flip_rate": len(flipped) / n if n else 0.0,
        "flipped_ids": flipped[:16],
        "lone_solver": lone,
    }


ABOUT = """
<p>Five phrasings of the same task, one model, temperature 0. Everything downstream of the
prompt is held fixed, so the spread is caused by wording and nothing else.</p>
<p>This is the input half of a pair. The <code>code-eval-harness</code> repo measured the
output half: identical generations score anywhere from 0% to 94% depending only on how code
is extracted from the response. Between them they bracket how much of a published pass@1
belongs to the harness.</p>
<p>The flip count is the number to read. A task solved under one phrasing and not another
was never measuring whether the model can write that function.</p>
"""

app = create_app(
    slug="prompt-shapes",
    icon="🖋",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=60,
            min=10,
            max=250,
            hint="each task is generated five times, once per phrasing",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
