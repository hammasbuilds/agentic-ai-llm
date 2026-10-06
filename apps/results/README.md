# Committed run summaries

Counts, not artifacts. Each file is the integers one measured run produced — totals,
survivor counts, per-kind tallies — in a few hundred bytes. The run artifacts
themselves (per-problem rows, generations, witnesses) are not committed, because
reproducing one needs Ollama, both model sizes and a GPU.

The summaries are here so that every number an app prints has a source in the
repository. `tests/test_documented_rates.py` reads them and checks the app's module
docstring, its ABOUT panel and the root README against them — separately, because
joined they cover for each other.

| File | What it summarises | Needs a model? |
|---|---|---|
| `02_false_accepts.json` | Mutation survival over both MBPP splits, 5,608 mutants in all | No |
| `03_vuln_baseline.json` | The Devign test split's class balance and two sampling windows | No |

Eight of the ten apps are not here. Their numbers come from runs that needed both
model sizes on a GPU, so there is nothing offline to check them against, and the
tests skip them **by name** rather than passing quietly. The count covered is
asserted, so it cannot drift to zero unnoticed.

A summary is written by running the app's `runner` over the full population and
keeping the scalar fields. It is replaced when the app is re-measured, never
hand-edited: a number in one of these files that no run produced is the defect this
directory exists to prevent.
