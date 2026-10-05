"""Command line for log-detective. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .templates import extract, sweep


def _read(paths: list[str]) -> list[str]:
    lines: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for f in sorted(path.glob("*.log")):
                lines += f.read_text(encoding="utf-8", errors="replace").splitlines()
        elif path.is_file():
            lines += path.read_text(encoding="utf-8", errors="replace").splitlines()
        else:
            print(f"no such path: {path}", file=sys.stderr)
    return lines


def _templates_command(args: argparse.Namespace) -> int:
    lines = _read(args.paths)
    if not lines:
        return 2
    result = extract(lines, threshold=args.threshold)

    print(
        f"{result.lines:,} lines -> {len(result.templates)} templates "
        f"({result.compression:.1f}x) at threshold {result.threshold}"
    )
    print(
        f"  {len(result.merged_templates)} template(s) merged distinct messages; "
        f"{result.distinct_messages_lost} distinction(s) lost"
    )
    print()
    for template in result.templates[: args.limit]:
        flag = " MERGED" if template.merged else ""
        print(f"  {template.count:6d}x{flag}  {template.text[:96]}")
        if template.merged and args.verbose:
            for example in template.examples(3):
                print(f"            was: {example[:88]}")
    return 0


def _cost_command(args: argparse.Namespace) -> int:
    """Compression against what it destroys. The point of the tool."""
    lines = _read(args.paths)
    if not lines:
        return 2
    print(f"{len(lines):,} lines\n")
    print(
        f"{'thresh':>7s} {'templates':>10s} {'compression':>12s} "
        f"{'merged':>7s} {'distinct lost':>14s} {'singletons':>11s}"
    )
    rows = sweep(lines)
    for result in rows:
        print(
            f"{result.threshold:7.1f} {len(result.templates):10d} "
            f"{result.compression:11.1f}x {len(result.merged_templates):7d} "
            f"{result.distinct_messages_lost:14d} {len(result.singletons):11d}"
        )
    print()
    print("  'distinct lost' counts messages that no longer have a template of")
    print("  their own. Compression is bought by deciding two lines are the same.")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "threshold": r.threshold,
                        "templates": len(r.templates),
                        "compression": round(r.compression, 3),
                        "merged_templates": len(r.merged_templates),
                        "distinct_messages_lost": r.distinct_messages_lost,
                        "singletons": len(r.singletons),
                    }
                    for r in rows
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 0


def _rare_command(args: argparse.Namespace) -> int:
    """The lines that happened once. Usually the reason you opened the log."""
    lines = _read(args.paths)
    if not lines:
        return 2
    result = extract(lines, threshold=args.threshold)
    rare = result.rarest(args.limit)
    print(
        f"{len(result.singletons)} template(s) seen exactly once, of {len(result.templates)}\n"
    )
    for template in rare:
        print(f"  {template.count:4d}x  line {template.first_line:6d}  {template.text[:88]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="log-detective",
        description="Extract log templates, and report what the extraction destroyed.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("templates", help="extract templates at one threshold")
    t.add_argument("paths", nargs="+")
    t.add_argument("--threshold", type=float, default=0.6)
    t.add_argument("--limit", type=int, default=25)
    t.add_argument("--verbose", "-v", action="store_true")
    t.set_defaults(func=_templates_command)

    c = sub.add_parser("cost", help="compression against information destroyed")
    c.add_argument("paths", nargs="+")
    c.add_argument("--json")
    c.set_defaults(func=_cost_command)

    r = sub.add_parser("rare", help="templates seen once or twice")
    r.add_argument("paths", nargs="+")
    r.add_argument("--threshold", type=float, default=0.6)
    r.add_argument("--limit", type=int, default=15)
    r.set_defaults(func=_rare_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
