"""Size Curve — where does a 5x bigger coder model actually pay?

qwen2.5-coder ships at 3B and 14B: same family, same training recipe, same tokenizer. That
makes the comparison clean in a way that comparing across families never is.

"The 14B scores higher" is not useful. The useful question is *where* the extra 7.6 GB of
weights goes, so every task lands in one of four buckets: both sizes solve it, only the big
one, only the small one, or neither. If the advantage is concentrated in a small set, the 3B
is the correct engineering choice everywhere else and the average hides it.

Measured on 250 MBPP tasks: 3B 60.0%, 14B 76.0%. But **of the 198 tasks either size can
solve, the 3B already handles 75.8%**, the 14B's whole advantage is 48 tasks, and it *loses*
8 the 3B gets right — which bounds how much of the 16-point gap is signal.
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
SLUG = "size-curve"
SIZES = ["qwen2.5-coder:3b", "qwen2.5-coder:14b"]

PROMPT = """Write a Python function for this task.

Task: {prompt}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 80))
    tasks = load("mbpp", limit)
    n = len(tasks)
    prompts = [PROMPT.format(prompt=t.prompt, test=t.tests[0]) for t in tasks]
    loop = asyncio.get_running_loop()

    passed: dict[str, set[str]] = {}
    pass_rate: dict[str, float] = {}
    for si, size in enumerate(SIZES):

        async def progress(done: int, total: int, _s=size, _i=si) -> None:
            # Two models, so the bar spans both halves of the run.
            await emit(_i * total + done, 2 * total, f"{_s}: {done}/{total}")

        raws = await model.generate_many(prompts, model=size, on_progress=progress)
        codes = [extract_code(r) for r in model.require_all(raws, what=f"{size} answer")]
        outs = await asyncio.gather(
            *[
                loop.run_in_executor(None, run_tests, c, list(t.tests), t.setup)
                for c, t in zip(codes, tasks, strict=True)
            ]
        )
        ok = {t.task_id for t, o in zip(tasks, outs, strict=True) if o.passed}
        passed[size] = ok
        pass_rate[size] = len(ok) / n if n else 0.0
        await emit((si + 1) * n, 2 * n, f"{size}: pass@1 {pass_rate[size]:.1%}")

    small, big = passed[SIZES[0]], passed[SIZES[1]]
    ids = {t.task_id for t in tasks}
    buckets = {
        "both": sorted(small & big),
        "big_only": sorted(big - small),
        "small_only": sorted(small - big),
        "neither": sorted(ids - small - big),
    }
    either = len(small | big)

    return {
        "n": n,
        "small_model": SIZES[0],
        "big_model": SIZES[1],
        "small_pass": pass_rate[SIZES[0]],
        "big_pass": pass_rate[SIZES[1]],
        "gap": pass_rate[SIZES[1]] - pass_rate[SIZES[0]],
        "buckets": {k: len(v) for k, v in buckets.items()},
        "bucket_ids": {k: v[:12] for k, v in buckets.items()},
        "small_share_of_solvable": len(small) / either if either else 0.0,
        "solvable": either,
    }


ABOUT = """
<p>Same prompt, same tests, same execution rule — only the parameter count changes.</p>
<p>On 250 MBPP tasks the 3B scores 60.0% and the 14B 76.0%. The four buckets are where the
useful reading is: <b>142 tasks both sizes solve</b>, 48 only the 14B, <b>8 only the 3B</b>,
and 52 neither.</p>
<p>So of everything either size can do, the small model already does 75.8%. The 14B's entire
advantage is 19.2% of the benchmark, and the 8 tasks it loses put a floor under how much of
the gap is noise rather than capability.</p>
<p>That reframes the deployment question. Not "which model is better" but "is 19.2% of tasks
worth five times the weights and the VRAM" — and the aggregate score cannot answer it.</p>
"""

app = create_app(
    slug="size-curve",
    icon="📐",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=80,
            min=10,
            max=400,
            hint="each task is generated twice, once per model size",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
    model="qwen2.5-coder:3b",
)
