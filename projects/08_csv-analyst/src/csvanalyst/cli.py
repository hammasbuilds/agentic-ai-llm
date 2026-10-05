"""Command line for csv-analyst. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .charts import bars, histogram
from .execute import column_summary, contamination_findings, load
from .narrate import narrate
from .profile import honest_mean, naive_mean, profile_csv


def _analyse(path: Path, limit: int | None):
    profile = profile_csv(path, limit=limit)
    conn = load(path, profile, limit=limit)
    findings = column_summary(conn, profile) + contamination_findings(conn, profile)
    return profile, conn, findings


def _report_command(args: argparse.Namespace) -> int:
    path = Path(args.csv)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    profile, _, findings = _analyse(path, args.limit)
    print(narrate(profile, findings))
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "path": profile.path,
                    "rows": profile.rows,
                    "duplicate_rows": profile.duplicate_rows,
                    "ragged_rows": profile.ragged_rows,
                    "columns": [asdict(c) for c in profile.columns],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


def _charts_command(args: argparse.Namespace) -> int:
    path = Path(args.csv)
    profile = profile_csv(path, limit=args.limit)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    import csv as _csv

    text = path.read_text(encoding="utf-8", errors="replace")
    reader = _csv.reader(text.splitlines(), delimiter=profile.delimiter)
    next(reader, [])  # advance past the header row; its contents are not used here
    rows = list(reader)[: args.limit] if args.limit else list(reader)

    written = 0
    for column in profile.columns:
        values = [r[column.index] for r in rows if column.index < len(r)]
        if column.kind == "numeric" and not column.is_contaminated:
            from .profile import parse_number

            nums = [n for n in (parse_number(v) for v in values) if n is not None]
            svg = histogram(nums, f"{column.name} (n={len(nums):,})")
        elif column.top_values:
            svg = bars(
                [(v, float(n)) for v, n in column.top_values],
                f"{column.name}: most common",
            )
        else:
            continue
        safe = "".join(ch if ch.isalnum() else "_" for ch in column.name)
        (out_dir / f"{safe}.svg").write_text(svg, encoding="utf-8")
        written += 1

    print(f"wrote {written} chart(s) to {out_dir}")
    return 0


def _coercion_command(args: argparse.Namespace) -> int:
    """Show what a silent numeric cast costs, column by column.

    This is the demonstration the project is built around: the difference
    between a mean and the same mean with its denominator stated.
    """
    path = Path(args.csv)
    profile = profile_csv(path, limit=args.limit)

    import csv as _csv

    text = path.read_text(encoding="utf-8", errors="replace")
    reader = _csv.reader(text.splitlines(), delimiter=profile.delimiter)
    next(reader, None)
    rows = list(reader)[: args.limit] if args.limit else list(reader)

    print(f"{'column':18s} {'naive mean':>15s} {'used':>9s} {'dropped':>9s}  note")
    print("-" * 82)
    for column in profile.columns:
        if column.kind != "numeric":
            continue
        values = [r[column.index] for r in rows if column.index < len(r)]
        naive = naive_mean(values)
        mean, used, dropped = honest_mean(values)
        if naive is None:
            continue
        note = "silently drops a category" if column.is_contaminated else ""
        print(f"{column.name[:18]:18s} {naive:15,.3f} {used:9,d} {dropped:9,d}  {note}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csv-analyst",
        description="Profile a CSV, compute only what validates, and never narrate "
        "a number that was not computed.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("report", help="full profile and validated findings")
    r.add_argument("csv")
    r.add_argument("--limit", type=int, default=None, help="read at most N rows")
    r.add_argument("--json", help="also write the profile as JSON")
    r.set_defaults(func=_report_command)

    c = sub.add_parser("charts", help="write one SVG per column")
    c.add_argument("csv")
    c.add_argument("--out", default="out/charts")
    c.add_argument("--limit", type=int, default=None)
    c.set_defaults(func=_charts_command)

    x = sub.add_parser("coercion", help="what a silent numeric cast drops")
    x.add_argument("csv")
    x.add_argument("--limit", type=int, default=None)
    x.set_defaults(func=_coercion_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
