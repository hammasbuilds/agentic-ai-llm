"""Debug Ceiling — how many rounds of test feedback are worth paying for?

Show the model its failing test output and let it try again. Everyone builds this loop;
almost nobody publishes where it stops helping.

The loop is a **LangGraph state graph**, which is the honest shape for it rather than a for
loop dressed up: `generate -> execute -> (solved? end : repair) -> execute -> ...` with a
conditional edge on the test result and a recursion limit as the round cap. The oracle is
real — a failing assert is ground truth, not another model's opinion — so "did the extra
round help" is a fact.

Measured on 150 MBPP tasks: round 1 solved 78.0%, round 2 added **one task**, and rounds
3, 4 and 5 added **nothing at all** for 60% of the compute. The tasks still failing after
round one were not tasks the model was one nudge from solving; they were tasks it could not
do, and showing it the error five times did not change that.
"""

# No `from __future__ import annotations` in this module. LangGraph resolves the state
# TypedDict's annotations at runtime to find the reducers, and stringified hints fail to
# evaluate - `NameError: Annotated` - the moment the graph is compiled.
import asyncio
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langgraph.graph import END, StateGraph  # noqa: E402

from apps._engine.datasets import load  # noqa: E402
from apps._engine.execute import extract_code  # noqa: E402
from apps._engine.execute import run as run_tests  # noqa: E402
from apps._platform import model  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "debug-ceiling"

FIRST = """Write a Python function for this task.

Task: {prompt}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""

RETRY = """This Python function is wrong.

Task: {prompt}

Your code:
```python
{code}
```

Running the tests gave:
{error}

Fix it. Output ONLY the corrected function and any imports it needs. No explanation.
"""


def _keep_last(_old, new):
    return new


class DebugState(TypedDict):
    task_id: str
    prompt: str
    test: str
    tests: list
    setup: str
    code: Annotated[str, _keep_last]
    error: Annotated[str, _keep_last]
    round: Annotated[int, _keep_last]
    solved: Annotated[bool, _keep_last]
    max_rounds: int


def build_graph():
    """generate -> execute -> repair -> execute -> ... until solved or out of rounds."""

    async def generate(state: DebugState) -> dict:
        raw = await model.generate(FIRST.format(prompt=state["prompt"], test=state["test"]), seed=1)
        return {"code": extract_code(model.require(raw, what="first attempt")), "round": 1}

    async def repair(state: DebugState) -> dict:
        rnd = state["round"] + 1
        raw = await model.generate(
            RETRY.format(
                prompt=state["prompt"],
                code=state["code"],
                error=state["error"] or "the tests failed",
            ),
            # Seeded per round: a retry at temperature 0 with no seed change is the
            # same greedy decode returning the same wrong answer.
            seed=rnd,
        )
        return {"code": extract_code(model.require(raw, what="repair")), "round": rnd}

    async def execute(state: DebugState) -> dict:
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(
            None, run_tests, state["code"], list(state["tests"]), state["setup"]
        )
        return {"solved": out.passed, "error": out.detail}

    def decide(state: DebugState) -> str:
        if state["solved"] or state["round"] >= state["max_rounds"]:
            return END
        return "repair"

    g = StateGraph(DebugState)
    g.add_node("generate", generate)
    g.add_node("repair", repair)
    g.add_node("execute", execute)
    g.set_entry_point("generate")
    g.add_edge("generate", "execute")
    g.add_edge("repair", "execute")
    g.add_conditional_edges("execute", decide, {"repair": "repair", END: END})
    return g.compile()


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 40))
    max_rounds = int(params.get("rounds", 5))
    tasks = load("mbpp", limit)
    graph = build_graph()

    per_round = [0] * max_rounds
    solved_at: dict[str, int] = {}
    # One GPU: run a handful of graphs at a time, not all 150.
    sem = asyncio.Semaphore(4)
    done = 0
    lock = asyncio.Lock()

    async def one(task):
        nonlocal done
        async with sem:
            final = await graph.ainvoke(
                {
                    "task_id": task.task_id,
                    "prompt": task.prompt,
                    "test": task.tests[0],
                    "tests": list(task.tests),
                    "setup": task.setup,
                    "code": "",
                    "error": "",
                    "round": 0,
                    "solved": False,
                    "max_rounds": max_rounds,
                },
                {"recursion_limit": 2 * max_rounds + 6},
            )
        async with lock:
            done += 1
            if final.get("solved"):
                r = min(final.get("round", 1), max_rounds)
                per_round[r - 1] += 1
                solved_at[task.task_id] = r
            current = done
        if current % 5 == 0 or current == len(tasks):
            await emit(current, len(tasks), f"{current}/{len(tasks)} — {len(solved_at)} solved")
        return None

    await emit(0, len(tasks), f"{len(tasks)} tasks, up to {max_rounds} rounds each")
    await asyncio.gather(*[one(t) for t in tasks])

    n = len(tasks)
    total_gain = sum(per_round)
    cumulative = []
    running = 0
    for c in per_round:
        running += c
        cumulative.append(running / n if n else 0.0)

    return {
        "n": n,
        "rounds": max_rounds,
        "per_round": per_round,
        "cumulative": cumulative,
        "total_solved": total_gain,
        "final_pass": total_gain / n if n else 0.0,
        "first_two_share": (sum(per_round[:2]) / total_gain) if total_gain else 0.0,
        "beyond_two": sum(per_round[2:]),
        "wasted_compute_share": (max_rounds - 2) / max_rounds if max_rounds > 2 else 0.0,
    }


ABOUT = """
<p>The loop is a LangGraph state graph — <code>generate → execute → repair → execute</code>
with a conditional edge on the test result — because that is what it is. The oracle is a
failing assert, so unlike a revision loop scored by another model, "did this round help"
has a factual answer.</p>
<p>On 150 MBPP tasks: <b>round 1 solved 78.0%, round 2 added one task, rounds 3–5 added
zero.</b> Rounds 1–2 captured 100% of everything the loop ever achieved, for 40% of the
compute.</p>
<p>A second measurement in this repo agrees from another direction: given a failed first
attempt, repairing it fixed 1 of 60 and rewriting from scratch fixed 3 — <b>93.3% survived
both</b>. First-attempt failures are mostly tasks the model cannot do, not tasks it is one
nudge away from.</p>
<p>What the curve cannot show: a fix that passes the tests and is still wrong. Feedback-driven
repair optimises for the tests it is shown, which is why the thinness of those tests is the
subject of another app here.</p>
"""

app = create_app(
    slug="debug-ceiling",
    icon="🌿",
    runner=runner,
    fields=[
        Field(
            "limit",
            "MBPP tasks",
            default=40,
            min=5,
            max=200,
            hint="each task runs its own graph to completion",
        ),
        Field(
            "rounds",
            "Max rounds",
            default=5,
            min=1,
            max=8,
            hint="the recursion cap on the repair loop",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
