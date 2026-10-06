"""Command line for repo-cartographer.

Uses argparse rather than Typer or Click: the core has no dependencies and the
CLI should not be the thing that introduces one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .graph import build_graph
from .parse import parse_repo
from .report import build_report, impact_of, render_text, report_from_graph


def _map_command(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    report = build_report(root, top=args.top)
    if args.json:
        out = report.to_json()
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
            print(f"wrote {args.output}")
        else:
            print(out)
    else:
        print(render_text(report))
    return 0


def _impact_command(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    graph = build_graph(parse_repo(root))

    target = args.symbol
    if target not in graph.by_qualname:
        matches = [q for q in graph.by_qualname if q.endswith(f".{target}") or target in q]
        if not matches:
            print(f"no definition matching {target!r}", file=sys.stderr)
            return 1
        if len(matches) > 1 and target not in matches:
            print(f"{target!r} is ambiguous, did you mean:", file=sys.stderr)
            for m in sorted(matches)[:10]:
                print(f"  {m}", file=sys.stderr)
            return 1
        target = matches[0]

    layers = impact_of(graph, target, depth=args.depth)
    sym = graph.by_qualname[target]
    print(f"{target}  ({sym.path}:{sym.line})")
    if not layers:
        print("  nothing in this repo calls it - it is an entry point or dead code.")
        return 0
    total = sum(len(v) for v in layers.values())
    print(f"  blast radius: {total} definitions within {args.depth} hops\n")
    for hop, callers in layers.items():
        print(f"  {hop}  ({len(callers)})")
        for c in callers[:12]:
            print(f"    {c}")
        if len(callers) > 12:
            print(f"    ... and {len(callers) - 12} more")
    return 0


def _compare_command(args: argparse.Namespace) -> int:
    """Map several repositories at once, one line each.

    Built for the portfolio case: point it at a folder of checkouts and see
    which of them actually resolve, and how big each really is.
    """
    parent = Path(args.parent).resolve()
    repos = sorted(d for d in parent.iterdir() if d.is_dir() and not d.name.startswith("."))
    rows = []
    for d in repos:
        try:
            graph = build_graph(parse_repo(d))
        except Exception as exc:  # a broken checkout must not stop the sweep
            rows.append((d.name, None, str(exc)))
            continue
        if not graph.repo.modules:
            continue
        rows.append((d.name, report_from_graph(graph, top=1), None))

    # Both columns, because the gap between them IS the finding. A table of only
    # repo-internal rates cannot show that the all-call-sites metric is the broken one.
    print(
        f"{'repo':28s} {'mods':>5s} {'defs':>6s} {'lines':>8s} "
        f"{'all-calls':>10s} {'repo-calls':>11s}  core module"
    )
    print("-" * 96)
    for name, rep, err in rows:
        if err:
            print(
                f"{name:28s} {'-':>5s} {'-':>6s} {'-':>8s} {'-':>10s} {'-':>11s}  "
                f"error: {err[:30]}"
            )
            continue
        core = rep.core_modules[0].module if rep.core_modules else "-"
        print(
            f"{name:28s} {rep.modules:5d} {rep.symbols:6d} {rep.loc:8,d} "
            f"{rep.resolution_rate:9.0%} {rep.repo_resolution_rate:10.0%}  {core}"
        )

    # The summary the README quotes. It used to quote a median that nothing here
    # computed - `grep -rni median src/` found nothing - so the headline number had no
    # source in the tool that was supposed to produce it. Empty checkouts were skipped
    # silently and never counted, which is the denominator doing quiet work.
    measured = [rep for _, rep, err in rows if rep is not None and err is None]
    rates = sorted(rep.repo_resolution_rate for rep in measured)
    failed = [name for name, rep, err in rows if err]
    empty = len(repos) - len(measured) - len(failed)
    print("-" * 96)
    if rates:
        middle = len(rates) // 2
        median = rates[middle] if len(rates) % 2 else (rates[middle - 1] + rates[middle]) / 2
        all_rates = sorted(rep.resolution_rate for rep in measured)
        a_mid = len(all_rates) // 2
        all_median = (
            all_rates[a_mid]
            if len(all_rates) % 2
            else (all_rates[a_mid - 1] + all_rates[a_mid]) / 2
        )
        print(
            f"{len(measured)} repositories measured, "
            f"{sum(1 for r in rates if r >= 0.90)} at or above 90%, "
            f"median {median:.0%} repo-internal against {all_median:.0%} over all call sites"
        )
        print(
            f"{sum(rep.modules for rep in measured):,} modules, "
            f"{sum(rep.loc for rep in measured):,} lines, "
            f"{sum(len(rep.parse_errors) for rep in measured)} file(s) that did not parse"
        )
    print(f"{empty} checkout(s) held no Python and were skipped; {len(failed)} failed to read")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cartographer",
        description="Map an unfamiliar Python codebase from its AST.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("map", help="map one repository")
    m.add_argument("repo", help="path to the repository")
    m.add_argument("--json", action="store_true", help="emit JSON instead of text")
    m.add_argument("--output", "-o", help="write JSON to this path")
    m.add_argument("--top", type=int, default=12, help="entries per section")
    m.set_defaults(func=_map_command)

    i = sub.add_parser("impact", help="what breaks if this definition changes")
    i.add_argument("repo", help="path to the repository")
    i.add_argument("symbol", help="qualified or partial name")
    i.add_argument("--depth", type=int, default=3, help="hops to follow")
    i.set_defaults(func=_impact_command)

    c = sub.add_parser("compare", help="map every repository under a folder")
    c.add_argument("parent", help="folder containing checkouts")
    c.set_defaults(func=_compare_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
