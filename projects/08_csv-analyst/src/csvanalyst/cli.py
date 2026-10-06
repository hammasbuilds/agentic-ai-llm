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


#: What this sweep will try to read. Anything else is counted and named rather than
#: skipped in silence - a sweep whose denominator quietly shrinks is the defect this
#: whole tool is about.
SWEEPABLE = frozenset({".csv", ".tsv", ".txt", ".data"})

#: ARFF is not delimited text with a header row: it opens with `@relation`,
#: `@attribute` lines and `@data`. Profiling one as a CSV produced a single column
#: literally named "@relation freMTPL2freq" and then reported it as a contaminated
#: numeric column - which took the corpus total from 2 to 4, both of them parse
#: artefacts of this tool rather than anything in the file.
NOT_DELIMITED_PREFIXES = ("@", "%", "<", "{", "#!")


def _looks_delimited(path: Path) -> bool:
    """Whether the first non-blank line could be a header row."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    return not line.lstrip().startswith(NOT_DELIMITED_PREFIXES)
    except OSError:
        return False
    return False


def _sweep_command(args: argparse.Namespace) -> int:
    """Profile every delimited file under a folder and print the corpus table.

    The README quoted this table - files, columns profiled, warnings raised, the
    largest file and its duplicate rows - over "13 real datasets", and nothing here
    computed it. A count no command produces cannot go stale visibly, and this one
    had: the folder holds 18 files.
    """
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"{folder} is not a directory", file=sys.stderr)
        return 2

    rows = []
    unreadable: list[tuple[str, str]] = []
    files = sorted(f for f in folder.iterdir() if f.is_file())
    candidates = [f for f in files if f.suffix.lower() in SWEEPABLE and _looks_delimited(f)]
    chosen = set(candidates)
    others = [f.name for f in files if f not in chosen]

    for found in candidates:
        try:
            rows.append((found.name, profile_csv(found, limit=args.limit)))
        except Exception as exc:  # noqa: BLE001 — a bad file is data, not a crash
            unreadable.append((found.name, f"{type(exc).__name__}: {exc}"))

    if not rows:
        print("no delimited files profiled")
        return 0

    biggest = max(rows, key=lambda r: r[1].rows)
    contaminated = [(name, column.name) for name, prof in rows for column in prof.contaminated]
    print(f"{'file':34} {'rows':>10} {'cols':>5} {'warn':>5} {'dupes':>8}  contaminated")
    print("-" * 86)
    for name, prof in rows:
        bad = ", ".join(c.name for c in prof.contaminated) or "-"
        print(
            f"{name[:34]:34} {prof.rows:10,} {len(prof.columns):5} "
            f"{len(prof.all_warnings):5} {prof.duplicate_rows:8,}  {bad}"
        )
    print("-" * 86)
    print(f"Files profiled                 {len(rows)}")
    print(f"Columns profiled               {sum(len(p.columns) for _, p in rows)}")
    print(f"Warnings raised                {sum(len(p.all_warnings) for _, p in rows)}")
    print(f"Largest file                   {biggest[1].rows:,} rows ({biggest[0]})")
    print(
        f"Exact duplicate rows in it     {biggest[1].duplicate_rows:,} "
        f"({biggest[1].duplicate_rows / biggest[1].rows * 100:.1f}%)"
    )
    print(f"Contaminated numeric columns   {len(contaminated)}")
    for name, column in contaminated:
        print(f"                                 {name}: {column}")
    if others:
        print(f"\n{len(others)} file(s) are not delimited text and were not profiled:")
        print(f"    {', '.join(others)}")
    if unreadable:
        print(f"\n{len(unreadable)} file(s) could not be profiled:")
        for name, why in unreadable:
            print(f"    {name}: {why}")
    return 0


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
    short = sum(1 for r in rows if any(c.index >= len(r) for c in profile.columns))
    if short:
        print(f"note: {short:,} of {len(rows):,} row(s) are short; their missing cells are")
        print("      absent from the charts for the columns they do not reach")
    for column in profile.columns:
        values = [r[column.index] for r in rows if column.index < len(r)]
        if column.kind == "numeric" and not column.is_contaminated:
            from .profile import parse_number

            nums = [n for n in (parse_number(v) for v in values) if n is not None]
            # The title names both numbers. It used to name only the survivors, so a
            # histogram over a column where four values in five do not parse was
            # titled "n=1,200" with nothing to say that 4,800 had been dropped -
            # which is the exact silent exclusion the rest of this tool exists to
            # report.
            dropped = len(values) - len(nums)
            label = f"{column.name} (n={len(nums):,}" + (
                f" of {len(values):,}; {dropped:,} did not parse)" if dropped else ")"
            )
            svg = histogram(nums, label)
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

    w = sub.add_parser("sweep", help="profile every delimited file under a folder")
    w.add_argument("folder")
    w.add_argument("--limit", type=int, default=None, help="read at most N rows per file")
    w.set_defaults(func=_sweep_command)

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
