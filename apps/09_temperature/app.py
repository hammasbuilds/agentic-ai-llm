"""Temperature Lab — the temperature that maximises pass@1 is not the one that maximises pass@k.

Everyone knows this in the abstract and almost nobody reports the crossover, so people
benchmark at temperature 0 and then deploy an agent that samples ten times, or the reverse.

pass@1 rewards the single most likely answer, so low temperature wins. pass@k only needs one
of k samples to be right, so it rewards diversity — and greedy decoding produces none. At
temperature 0 all k samples are identical and pass@k equals pass@1 exactly, which this page
shows directly in the "distinct samples" column.

Scored with the unbiased estimator from the Codex paper, `1 - C(n-c, k) / C(n, k)`, rather
than "did any of my k samples pass", which is biased upward and shifts with how many you
happened to draw.
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
SLUG = "temperature"
TEMPS = [0.0, 0.4, 0.7, 1.0]

PROMPT = """Write a Python function for this task.

Task: {prompt}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k. `n` drawn, `c` correct."""
    if n - c < k:
        return 1.0
    prod = 1.0
    for i in range(k):
        prod *= (n - c - i) / (n - i)
    return 1.0 - prod


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 25))
    n_samples = int(params.get("samples", 5))
    tasks = load("mbpp", limit)
    loop = asyncio.get_running_loop()
    ks = [k for k in (1, 2, 5, 10) if k <= n_samples]

    table: dict[str, dict[str, float]] = {}
    diversity: dict[str, float] = {}
    step = 0
    total = len(TEMPS) * len(tasks)

    for temp in TEMPS:
        # Temperature 0 is deterministic: n samples are n identical answers, so draw one
        # and copy it rather than paying for duplicates.
        draws = 1 if temp == 0.0 else n_samples
        prompts, seeds = [], []
        for t in tasks:
            for s in range(draws):
                prompts.append(PROMPT.format(prompt=t.prompt, test=t.tests[0]))
                seeds.append(None if temp == 0.0 else s)

        raws = await model.generate_many(prompts, temperature=temp, seeds=seeds)
        flat = [extract_code(r) for r in model.require_all(raws, what=f"sample at {temp}")]

        correct, uniq = [], []
        for i, task in enumerate(tasks):
            got = flat[i * draws : (i + 1) * draws]
            codes = got * n_samples if draws == 1 else got
            outs = await asyncio.gather(
                *[
                    loop.run_in_executor(None, run_tests, c, list(task.tests), task.setup)
                    for c in codes
                ]
            )
            correct.append(sum(1 for o in outs if o.passed))
            uniq.append(len(set(codes)))

        table[str(temp)] = {
            str(k): sum(pass_at_k(n_samples, c, k) for c in correct) / len(tasks) for k in ks
        }
        diversity[str(temp)] = sum(uniq) / len(uniq) if uniq else 0.0
        step += len(tasks)
        await emit(
            step,
            total,
            f"T={temp}: pass@1 {table[str(temp)][str(ks[0])]:.1%}, "
            f"{diversity[str(temp)]:.1f} distinct of {n_samples}",
        )

    best_1 = max(TEMPS, key=lambda t: table[str(t)][str(ks[0])])
    best_k = max(TEMPS, key=lambda t: table[str(t)][str(ks[-1])])

    return {
        "n": len(tasks),
        "samples": n_samples,
        "ks": [str(k) for k in ks],
        "temps": [str(t) for t in TEMPS],
        "table": table,
        "diversity": diversity,
        "best_at_1": str(best_1),
        "best_at_k": str(best_k),
        "flips": best_1 != best_k,
        "k_label": str(ks[-1]),
        "cost_of_tuning_on_1": (table[str(best_k)][str(ks[-1])] - table[str(best_1)][str(ks[-1])]),
    }


ABOUT = """
<p>A temperature sweep against k, scored with the unbiased pass@k estimator rather than
"did any of my samples pass".</p>
<p>The mechanism is visible in the distinct-samples column: at temperature 0 every draw is
identical, so pass@10 cannot exceed pass@1 no matter how many you take. Raising temperature
buys diversity, which pass@k rewards and pass@1 punishes.</p>
<p>Where the two optima differ, tuning on one metric and deploying with the other leaves
measurable accuracy on the table — and that is the practical reason to print both.</p>
"""

app = create_app(
    slug="temperature",
    icon="🌡",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=25,
            min=5,
            max=100,
            hint="each task is sampled several times at each temperature",
        ),
        Field(
            "samples",
            "Samples per task",
            default=5,
            min=2,
            max=10,
            hint="k is capped by this; temperature 0 draws once and copies",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
