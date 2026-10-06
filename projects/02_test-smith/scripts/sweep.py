"""Measure several repositories and print one row each.

Used to produce the numbers in the README. Every figure there came out of this
script on this machine; none was estimated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from testsmith.runner import run  # noqa: E402

REPOS = [
    "urdu-nlp-toolkit",
    "credit-risk-engine",
    "deep-research-agent",
    "demand-forecast-platform",
    "insurance-mlops",
    "pak-law-assistant",
    "incident-copilot",
    "doc-intelligence-api",
]

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40
# Sibling checkouts live beside the monorepo, so that is the default. It used to be
# `~/code`, which does not exist on the machine the README's table was measured on -
# so the documented reproduction printed "missing" eight times, skipped the table and
# the summary because `rows` was empty, and exited 0. A green run that measured
# nothing is the failure mode this whole project is about.
ROOT = Path(
    os.environ.get("REPOS_ROOT") or Path(__file__).resolve().parents[3].parent
).expanduser()

print(
    f"{'repo':26s} {'mut':>4s} {'kill':>4s} {'live':>4s} {'err':>4s} "
    f"{'score':>6s} {'cov-score':>9s} {'live/cov':>8s}"
)
print("-" * 78)

rows = []
for name in REPOS:
    repo = ROOT / name
    if not repo.is_dir():
        print(f"{name:26s} missing")
        continue
    try:
        r = run(repo, limit=LIMIT)
    except Exception as exc:
        print(f"{name:26s} error: {str(exc)[:40]}")
        continue
    rows.append((name, r))
    print(
        f"{name:26s} {len(r.results):4d} {r.killed:4d} {r.survived:4d} {r.errored:4d} "
        f"{r.score:6.0%} {r.covered_score:9.0%} {len(r.survivors_on_covered_lines):8d}",
        flush=True,
    )

if not rows:
    print("-" * 78)
    print(f"No repository was measured. Looked in {ROOT}", file=sys.stderr)
    print(
        "Set REPOS_ROOT to the folder holding these checkouts, or run this from a "
        "clone that sits beside them.",
        file=sys.stderr,
    )
    raise SystemExit(1)

if rows:
    import statistics

    print("-" * 78)
    scores = [r.score for _, r in rows]
    cov_scores = [r.covered_score for _, r in rows]
    total_live_cov = sum(len(r.survivors_on_covered_lines) for _, r in rows)
    print(
        f"repos={len(rows)}  median score={statistics.median(scores):.0%}  "
        f"median covered-line score={statistics.median(cov_scores):.0%}"
    )
    print(f"survivors on executed lines, total = {total_live_cov}")

    by_op: dict[str, list[int]] = {}
    for _, r in rows:
        for op, (caught, scored) in r.by_operator.items():
            slot = by_op.setdefault(op, [0, 0])
            slot[0] += caught
            slot[1] += scored
    print("\noperator     caught/scored   rate")
    for op, (c, s) in sorted(by_op.items(), key=lambda kv: -kv[1][1]):
        print(f"  {op:10s} {c:4d}/{s:<4d}      {c / s:.0%}" if s else f"  {op:10s} n/a")
