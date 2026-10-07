"""Command line for test-smith. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .mutate import generate
from .report import render_text, write_json
from .runner import run, source_files


def _progress(i: int, n: int, mutant, outcome: str) -> None:
    mark = {"killed": "kill", "survived": "LIVE", "timeout": "slow", "error": "err "}[outcome]
    print(f"  [{i:4d}/{n}] {mark}  {mutant.label}", flush=True)


def _run_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2
    try:
        report = run(
            repo,
            limit=args.limit,
            only=args.only,
            progress=None if args.quiet else _progress,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print()
    print(render_text(report))
    if args.json:
        write_json(report, Path(args.json))
        print(f"wrote {args.json}")
    return 0


def _preview_command(args: argparse.Namespace) -> int:
    """List the mutants that would be run, without running anything.

    Useful before committing to a long run, and the only safe way to inspect a
    repository whose suite does not currently pass.
    """
    repo = Path(args.repo).resolve()
    # `_run_command` refuses a path that is not a directory, with exit 2; this one did
    # not, and printed "0 mutants across the repository" with exit 0 for a typo. The
    # two commands take the same argument and have to answer it the same way.
    if not repo.is_dir():
        what = "no such directory" if not repo.exists() else "not a directory"
        print(f"{what}: {args.repo}", file=sys.stderr)
        return 2
    if not source_files(repo):
        print(f"nothing to mutate: no Python files under {args.repo}", file=sys.stderr)
        return 2
    total = 0
    for f in source_files(repo):
        rel = f.relative_to(repo).as_posix()
        if args.only and args.only not in rel:
            continue
        mutants = generate(f, rel)
        if not mutants:
            continue
        total += len(mutants)
        print(f"{rel}  ({len(mutants)} mutants)")
        if args.verbose:
            for m in mutants:
                print(f"    {m.line:5d}  {m.operator:9s} {m.before} -> {m.after}")
    print(f"\n{total} mutants across the repository")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="testsmith",
        description="Mutation testing: does the suite catch a change, or merely run the line?",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="mutate and measure")
    r.add_argument("repo")
    r.add_argument("--limit", type=int, default=None, help="cap mutants, sampled across files")
    r.add_argument("--only", help="restrict to paths containing this substring")
    r.add_argument("--json", help="also write the report as JSON")
    r.add_argument("--quiet", action="store_true", help="suppress per-mutant output")
    r.set_defaults(func=_run_command)

    v = sub.add_parser("preview", help="list mutants without running the suite")
    v.add_argument("repo")
    v.add_argument("--only")
    v.add_argument("--verbose", "-v", action="store_true")
    v.set_defaults(func=_preview_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
