"""False Accepts — how much wrong code do three assert statements let through?

MBPP specifies each problem with exactly three asserts. Break the reference solution in one
place and run the same three asserts: if they still pass, the benchmark cannot tell the
reference from a program that is not it.

Survival alone overstates the problem, because some mutations are equivalent to the original
and no test could catch them. So every survivor is hunted for a **separating input** - a
value on which the mutant and the reference return different things. A survivor with a
witness is a provably wrong program that MBPP marked correct; one without is reported as
unproven rather than counted.

Measured over the whole benchmark: 18.0% of 4,055 mutants survive, and 362 of them are
provably wrong. 326 of the 971 usable problems accept at least one. The hand-verified
"sanitized" split is no better - 16.5% of 1,553 - because reviewing an assert cannot add the
fourth assert that would pin down a boundary.

Every rate here is over the problems whose reference passes its own tests and whose tests
name a function to run it against: 971 of MBPP's 974 rows and 413 of the sanitized split's
427. Three numbers, not one, and they were being published as one:

  * 974 and 427 are what the committed slices hold;
  * 972 and 413 are what `load_mbpp` can use - it skips a row whose tests never call a
    function by name, because there is then nothing to run the reference against. Two
    rows and fourteen rows, named in `data/benchmarks/README.md`;
  * 971 is the full split's usable rows minus the one whose reference fails its own
    tests, and a mutant of a solution that is already failing says nothing about the
    suite.

The denominator every rate below is over is the last of those. It used to be written as
"971 of MBPP's 972 and all 413 of the sanitized split", which named one exclusion and
inherited sixteen.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.datasets import load  # noqa: E402
from apps._engine.differential import find_witness  # noqa: E402
from apps._engine.execute import run as run_tests  # noqa: E402
from apps._engine.mutate import mutants  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "false-accepts"


async def runner(params: dict, emit) -> dict:
    limit = int(params.get("limit", 60))
    per_problem = int(params.get("per_problem", 8))

    split = params.get("split") or "mbpp"
    tasks = load(split, limit)
    which = "sanitized MBPP" if split.endswith("sanitized") else "MBPP"
    await emit(0, limit, f"{len(tasks)} {which} problems, up to {per_problem} mutants each")

    rows: list[dict] = []
    kinds: dict[str, list[int]] = {}
    killed_how = {"fail": 0, "error": 0, "timeout": 0}

    # The population every rate below is over. The README used to quote "227 of 782
    # problems", and 782 is neither the number loaded nor the number whose reference
    # passes - nothing here produced it, so nothing could check it.
    usable = 0
    unusable: list[str] = []

    loop = asyncio.get_running_loop()
    for i, task in enumerate(tasks, 1):
        # The reference must pass its own tests or every mutant of it is meaningless.
        ref_ok = await loop.run_in_executor(
            None, run_tests, task.reference, list(task.tests), task.setup
        )
        if not ref_ok.passed:
            unusable.append(task.task_id)
            await emit(i, len(tasks), f"{task.task_id}: reference fails its own tests")
            continue
        usable += 1

        muts = mutants(task.reference, limit=per_problem)
        for m in muts:
            out = await loop.run_in_executor(None, run_tests, m.code, list(task.tests), task.setup)
            bucket = kinds.setdefault(m.kind, [0, 0])
            bucket[0] += 1
            if out.passed:
                bucket[1] += 1
                # Only survivors need a witness; a killed mutant is already decided.
                w = await loop.run_in_executor(
                    None,
                    find_witness,
                    task.reference,
                    m.code,
                    task.entry_point,
                    task.tests,
                    task.setup,
                )
                rows.append(
                    {
                        "task_id": task.task_id,
                        "kind": m.kind,
                        "where": m.where,
                        "entry_point": task.entry_point,
                        "proven": w.found,
                        "witness": (
                            {"args": w.args, "ref": w.ref, "mut": w.mut} if w.found else None
                        ),
                        # An unproven survivor is either equivalent or merely not
                        # separated by what was tried, and those were indistinguishable
                        # here because only `found` was kept. A survivor on which zero
                        # inputs ran is not evidence of anything.
                        "cases_run": w.cases_run,
                        "unproven_because": "" if w.found else w.reason,
                    }
                )
            elif out.status in killed_how:
                killed_how[out.status] += 1

        if i % 5 == 0 or i == len(tasks):
            surv = len(rows)
            await emit(i, len(tasks), f"{i}/{len(tasks)} problems — {surv} survivors so far")

    total = sum(v[0] for v in kinds.values())
    survived = sum(v[1] for v in kinds.values())
    proven = [r for r in rows if r["proven"]]
    killed = total - survived
    # The denominator behind "unproven". A survivor that no input was ever run against
    # sits in the same bucket as one that forty inputs failed to separate, and only one
    # of those is evidence about the mutant.
    unproven = [r for r in rows if not r["proven"]]
    never_tried = [r for r in unproven if r["cases_run"] == 0]

    return {
        "problems": len(tasks),
        "problems_usable": usable,
        "problems_whose_reference_fails": len(unusable),
        "problems_with_a_survivor": len({r["task_id"] for r in rows}),
        "mutants": total,
        "survived": survived,
        "survival_rate": survived / total if total else 0.0,
        "proven": len(proven),
        "proven_share_of_survivors": len(proven) / survived if survived else 0.0,
        "proven_share_of_all": len(proven) / total if total else 0.0,
        "unproven": len(unproven),
        "unproven_never_tried": len(never_tried),
        "unproven_tried_and_not_separated": len(unproven) - len(never_tried),
        "killed_how": killed_how,
        "caught_by_crash": (killed_how["error"] + killed_how["timeout"]) / killed
        if killed
        else 0.0,
        "by_kind": {
            k: {"run": v[0], "survived": v[1], "rate": v[1] / v[0] if v[0] else 0.0}
            for k, v in sorted(kinds.items(), key=lambda kv: -kv[1][0])
        },
        "witnesses": [r for r in proven][:14],
    }


ABOUT = """
<p>Single-point mutation of every reference solution, scored against the benchmark's own
three asserts, with a separating input hunted for each survivor.</p>
<p><b>18.0%</b> of 4,055 mutants survive across the full split. <b>362</b> of them are
provably wrong — an input exists on which they differ from the reference — which is 8.9% of
all mutants and 49.5% of the survivors. The other 369 are reported unproven, not counted:
342 were hunted without a separating input being found and 27 could not be tried. Per
problem: <b>326 of 971 (33.6%)</b> accept at least one survivor.</p>
<p>Off-by-one is what slips through. Constant nudges survive 27.0% of the time and
comparison mutations (<code>&lt;</code> to <code>&lt;=</code>) 25.9%, against 6.8% for a
swapped arithmetic operator and 4.1% for a negated condition. A swapped operator breaks the
answer loudly enough for three examples to notice; a boundary moved by one does not.</p>
<p>The sanitized split — 427 problems the authors hand-verified, 413 of them with tests
that name a function to run — scores 16.5% of 1,553
mutants, and 117 of
them (28.3%) still accept a survivor. Verification fixed the reference solutions and left
the false accepts alone, because the limit is the number of asserts, not their quality.</p>
"""

app = create_app(
    slug="false-accepts",
    icon="🧫",
    runner=runner,
    fields=[
        Field(
            "limit",
            "Problems",
            default=60,
            min=5,
            max=400,
            hint="MBPP problems to mutate; each runs its own tests many times",
        ),
        Field(
            "split",
            "Split",
            kind="select",
            default="mbpp",
            options=[
                ("mbpp", "the whole benchmark"),
                ("mbpp-sanitized", "the hand-verified subset"),
            ],
            hint="the sanitized split is the 427 problems the authors re-checked by hand; "
            "413 of them carry a test that names a function, which is what gets scored",
        ),
        Field(
            "per_problem",
            "Mutants per problem",
            default=8,
            min=1,
            max=16,
            hint="single-point changes: comparisons, operators, constants, conditions",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
