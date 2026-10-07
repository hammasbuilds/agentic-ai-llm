"""Command line for review-bot. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

from .checks import RULES
from .review import Review, render, review_diff, review_source
from .verify import FileContext

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        ".venvs",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "build",
        "dist",
        ".tox",
        ".eggs",
        "site-packages",
    }
)


def _python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    return sorted(
        p
        for p in target.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.relative_to(target).parts)
    )


def _diff_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    try:
        review = review_diff(repo, args.ref)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(render(review, show_retracted=args.show_retracted))
    if args.strict and review.confirmed:
        return 1
    return 0


def _scan_command(args: argparse.Namespace) -> int:
    """Review whole files rather than a diff. Used to measure precision.

    The two refusals below are the same failure in two shapes: a review of nothing
    printed as a review that found nothing. `scan C:/nope` resolved a path that does
    not exist, `rglob` over it yielded nothing, and the command printed
    `files=0 proposed=0 confirmed=0 retracted=0 (0%)` and exited 0 - a clean bill of
    health for a typo, with a retraction rate of 0% that reads as the tool's best
    possible result. A folder with no Python in it did the same thing.

    Nothing distinguishes those from a genuine clean review except the file count, and
    a reader who gets exit code 0 has already been told the answer.
    """
    target = Path(args.path).resolve()
    if not target.exists():
        print(f"no such file or directory: {args.path}", file=sys.stderr)
        return 2
    if not _python_files(target):
        what = "file is not Python" if target.is_file() else "directory holds no Python files"
        print(f"nothing to review: {what}: {args.path}", file=sys.stderr)
        return 2
    review = Review()
    skipped_tests = 0
    reviewed = 0
    unreadable = 0
    unparsed: list[str] = []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        for path in _python_files(target):
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                unreadable += 1
                continue
            if not args.include_tests and FileContext.build(str(path), source).is_test:
                skipped_tests += 1
                continue
            try:
                # Against the target's PARENT when the target is the file itself:
                # `Path('a/b.py').relative_to('a/b.py')` is `.`, so a single-file
                # scan listed its own parse error as `.` and named nothing.
                shown = str(path.relative_to(target.parent if target.is_file() else target))
            except ValueError:
                shown = str(path)
            file_review = review_source(shown, source)
            if not file_review.parsed:
                # Not reviewed: no rule ran over it. Counting it in `files=` put work
                # that did not happen into the denominator of every per-file figure.
                unparsed.append(shown)
                continue
            reviewed += 1
            if file_review.verdicts:
                review.files.append(file_review)

    print(render(review, show_retracted=args.show_retracted))
    # The denominator, which this command never printed. The README quoted
    # "SOURCE FILES ONLY: files=1,325 proposed=476 ..." in a format nothing here
    # produced, so the headline rate had no source in the tool that computes it -
    # and the file count, which is what makes a retraction rate readable, was not
    # available at all.
    scope = "ALL FILES" if args.include_tests else "SOURCE FILES ONLY"
    # The rate as a fragment, so the conditional cannot swallow the line it belongs
    # to - which it did on the first attempt, printing "(no proposals to retract)"
    # with the counts gone.
    rate = (
        f"({review.retraction_rate:.0%})"
        if review.retraction_rate is not None
        else "(no proposals, so no retraction rate)"
    )
    print(
        f"  {scope}: files={reviewed:,}  proposed={review.proposed}  "
        f"confirmed={review.confirmed}  retracted={review.retracted} {rate}"
    )
    if unreadable:
        print(f"  {unreadable} file(s) could not be read and are not in that count")
    if unparsed:
        shown = ", ".join(sorted(unparsed)[:3])
        more = f" and {len(unparsed) - 3} more" if len(unparsed) > 3 else ""
        print(
            f"  {len(unparsed)} file(s) are not parseable Python and are not in that "
            f"count: {shown}{more}"
        )
    if skipped_tests:
        print(f"  ({skipped_tests} test files skipped; pass --include-tests to review them)")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "proposed": review.proposed,
                    "confirmed": review.confirmed,
                    "retracted": review.retracted,
                    "retraction_rate": (
                        round(review.retraction_rate, 4)
                        if review.retraction_rate is not None
                        else None
                    ),
                    "files_reviewed": reviewed,
                    "test_files_skipped": skipped_tests,
                    "files_unreadable": unreadable,
                    "files_unparseable": len(unparsed),
                    "by_rule": {
                        k: {"proposed": p, "confirmed": c}
                        for k, (p, c) in review.by_rule().items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 0


def _rules_command(_: argparse.Namespace) -> int:
    from .verify import _DEFEATERS

    print("Proposers are deliberately over-eager. Each one has verifiers that")
    print("try to defeat it before anything is reported.\n")
    for rule in RULES:
        has = "yes" if rule in _DEFEATERS else "no"
        print(f"  {rule:24s} defeaters: {has}")
    print("\nA proposal survives only if no defeater applies. The retraction rate")
    print("is printed on every run, because it is the number that matters.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review-bot",
        description="Propose findings, then try to disprove each one. Report only survivors.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("diff", help="review what a change added")
    d.add_argument("repo")
    d.add_argument("--ref", default="HEAD~1", help="compare against this ref")
    d.add_argument("--show-retracted", action="store_true")
    d.add_argument("--strict", action="store_true", help="exit 1 if anything is reported")
    d.set_defaults(func=_diff_command)

    s = sub.add_parser("scan", help="review whole files, to measure precision")
    s.add_argument("path")
    s.add_argument("--include-tests", action="store_true")
    s.add_argument("--show-retracted", action="store_true")
    s.add_argument("--json")
    s.set_defaults(func=_scan_command)

    r = sub.add_parser("rules", help="list proposers and whether they have defeaters")
    r.set_defaults(func=_rules_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
