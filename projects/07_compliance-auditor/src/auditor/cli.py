"""Command line for compliance-auditor. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .controls import CONTROLS
from .report import audit_folder, audit_one, render_folder, render_repo, to_json


def _audit_command(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    if not target.is_dir():
        print(f"not a directory: {target}", file=sys.stderr)
        return 2

    if args.one:
        _, repo = audit_one(target)
        print(render_repo(repo))
        return 1 if (args.strict and repo.failures) else 0

    # A rate over nothing is not a rate. `apps/_platform/cache.py` states the rule
    # this follows: "a cache nobody asked anything of has no hit rate, and reporting
    # one as zero is the same claim as a cache that missed every time". This printed
    # `0 repositories  -  0/0 controls passed (0%)` for a folder holding none, which
    # reads as a folder that failed every control.
    audit = audit_folder(target)
    if not audit.repos:
        print(f"nothing to audit: no repositories under {target}", file=sys.stderr)
        return 2
    print(render_folder(audit))
    if args.json:
        Path(args.json).write_text(to_json(audit), encoding="utf-8")
        print(f"wrote {args.json}")
    failed = sum(1 for r in audit.repos if r.failures)
    return 1 if (args.strict and failed) else 0


def _policy_command(_: argparse.Namespace) -> int:
    """Print the policy the audit enforces, so it can be argued with."""
    print("Controls, and the policy each one checks:\n")
    for control in CONTROLS:
        print(f"  {control.id}")
        print(f"      {control.policy}")
    print("\nA control returns PASS only when a collector observed something.")
    print("Where nothing could be observed it returns inconclusive or n/a,")
    print("which are excluded from the compliance rate rather than counted as passes.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compliance-auditor",
        description="Check stated policy against collected evidence. No inferred compliance.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("audit", help="audit a folder of repositories")
    a.add_argument("path")
    a.add_argument("--one", action="store_true", help="treat the path as a single repository")
    a.add_argument("--json", help="also write the audit as JSON")
    a.add_argument("--strict", action="store_true", help="exit 1 if anything failed")
    a.set_defaults(func=_audit_command)

    y = sub.add_parser("policy", help="print the controls and what each asserts")
    y.set_defaults(func=_policy_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
