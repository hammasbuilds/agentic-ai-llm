"""Render a mutation run.

The report leads with the split between "never executed" and "executed and not
checked", because that split is the only thing mutation testing tells you that
a coverage report cannot.
"""

from __future__ import annotations

import json
from pathlib import Path

from .runner import RunReport


def to_dict(report: RunReport) -> dict:
    cov = report.coverage
    return {
        "repo": report.repo,
        "interpreter": report.interpreter,
        "baseline_seconds": report.baseline_seconds,
        "total_mutants_available": report.total_mutants,
        "mutants_run": len(report.results),
        "killed": report.killed,
        "survived": report.survived,
        "timed_out": report.timed_out,
        "errored": report.errored,
        "score": round(report.score, 4),
        "covered_score": round(report.covered_score, 4),
        "covered_mutants": report.covered_mutants,
        "executed_lines": cov.total if cov else 0,
        "survivors_on_covered_lines": [
            {
                "path": r.mutant.path,
                "line": r.mutant.line,
                "operator": r.mutant.operator,
                "before": r.mutant.before,
                "after": r.mutant.after,
            }
            for r in report.survivors_on_covered_lines
        ],
        "survivors_on_uncovered_lines": len(report.survivors_on_uncovered_lines),
        "by_operator": {
            k: {"caught": c, "scored": s, "rate": round(c / s, 3) if s else 0.0}
            for k, (c, s) in report.by_operator.items()
        },
        "skipped_files": report.skipped_files,
    }


def write_json(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(report), indent=2), encoding="utf-8")


def render_text(report: RunReport) -> str:
    w = 78
    out: list[str] = []
    add = out.append
    cov = report.coverage

    add("=" * w)
    add(
        f"  {report.repo}  -  {len(report.results)} mutants run "
        f"of {report.total_mutants} available"
    )
    add("=" * w)
    add("")
    add(f"  suite passes in {report.baseline_seconds}s before mutation")
    if cov:
        add(f"  {cov.total} lines executed by the suite")
    add("")
    add("  OUTCOMES")
    add(f"    killed    {report.killed:4d}")
    add(f"    survived  {report.survived:4d}")
    add(f"    timeout   {report.timed_out:4d}   (counted as caught)")
    add(f"    error     {report.errored:4d}   (excluded - broke the import, proves nothing)")
    add("")
    add("  SCORE")
    add(f"    overall            {report.score:.0%}  over {report.scored} scored mutants")
    add(
        f"    on executed lines  {report.covered_score:.0%}  over "
        f"{report.covered_mutants} mutants"
    )

    survivors = report.survivors_on_covered_lines
    add("")
    add("  THE FINDING - survivors on lines the suite executed")
    add("  A coverage report marks these lines green. The test ran them, the code")
    add("  was wrong, and nothing failed.")
    add("")
    if not survivors:
        add("    none - every executed line that could be mutated was checked.")
    else:
        for r in survivors[:15]:
            m = r.mutant
            add(f"    {m.path}:{m.line}")
            add(f"        {m.operator}: {m.before}  ->  {m.after}")
        if len(survivors) > 15:
            add(f"    ... and {len(survivors) - 15} more")

    uncovered = len(report.survivors_on_uncovered_lines)
    add("")
    add(f"  Also {uncovered} survivor(s) on lines no test ever reached - a coverage")
    add("  gap rather than a test-quality one.")

    by_op = report.by_operator
    if by_op:
        add("")
        add("  BY OPERATOR  (caught / scored)")
        for op, (caught, scored) in sorted(
            by_op.items(), key=lambda kv: kv[1][1], reverse=True
        ):
            rate = caught / scored if scored else 0
            add(f"    {op:10s} {caught:3d}/{scored:<3d}  {rate:.0%}")

    add("")
    add("=" * w)
    return "\n".join(out)
