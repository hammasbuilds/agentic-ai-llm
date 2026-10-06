"""Command line for db-surgeon. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .operations import classify_script, summarise
from .plan import build, render


def _read(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _check_command(args: argparse.Namespace) -> int:
    plan = build(
        name=args.name or Path(args.up).stem,
        schema=_read(args.schema),
        seed=_read(args.seed),
        up=_read(args.up),
        down=_read(args.down),
    )
    print(render(plan))

    if args.json:
        trip = plan.trip
        payload = {
            "name": plan.name,
            "verdict": plan.verdict,
            "safe": plan.safe,
            "error": plan.error,
            "schema_equivalent": trip.schema_equivalent if trip else None,
            "schema_restored": trip.schema_restored if trip else None,
            "data_restored": trip.data_restored if trip else None,
            "columns_reordered": trip.columns_reordered if trip else [],
            "columns_lost": trip.columns_lost if trip else [],
            "rows_lost": trip.rows_lost if trip else None,
            "up": [
                {"kind": o.kind, "category": o.category, "target": o.target, "reason": o.reason}
                for o in plan.up_operations
            ],
            "disagreements": plan.disagreements,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    if args.strict and not plan.safe:
        return 1
    return 0


def _classify_command(args: argparse.Namespace) -> int:
    """Static reading only. Runs nothing, so it works on a suspect migration."""
    operations = classify_script(_read(args.sql))
    for op in operations:
        print(f"  [{op.category:>10s}] {op.kind:26s} {op.target}")
        print(f"               {op.reason}")
    print()
    print(f"  {summarise(operations)}")
    print("  This is pattern matching, not a parser. `check` executes the")
    print("  migration and is the authority where the two disagree.")
    return 0


def _corpus_command(args: argparse.Namespace) -> int:
    """Run the bundled corpus - the numbers in the README."""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "migrations"))
    try:
        from corpus import CASES, SCHEMA, SEED  # type: ignore
    except ImportError:
        print("corpus not found; run from a checkout", file=sys.stderr)
        return 2

    plans = [build(name, SCHEMA, SEED, up, down) for name, up, down, _ in CASES]
    ran = [p for p in plans if p.trip is not None]
    hidden = [p for p in ran if p.trip.schema_equivalent and not p.trip.data_restored]

    # Three columns, because two were doing the work of three. The `schema` column
    # printed `schema_restored` - set equality AND original column order - while the
    # headline counted `schema_equivalent`, which ignores order. So "drop an unused
    # column" read NO in the table and was one of the three in the count, and the same
    # output disagreed with itself. `order` is now its own column: a schema-diff tool
    # compares column sets, so `schema` is what such a tool would pass, and whether the
    # order survived is reported beside it rather than folded in.
    print(f"{'migration':36s} {'schema':>7s} {'order':>6s} {'data':>6s}  verdict")
    print("-" * 82)
    for plan in plans:
        if plan.trip is None:
            print(f"{plan.name:36s} {'-':>7s} {'-':>6s} {'-':>6s}  did not run")
            continue
        trip = plan.trip
        print(
            f"{plan.name:36s} {'ok' if trip.schema_equivalent else 'NO':>7s} "
            f"{'ok' if not trip.columns_reordered else 'MOVED':>6s} "
            f"{'ok' if trip.data_restored else 'LOST':>6s}  {plan.verdict}"
        )
    print("-" * 82)
    print(
        f"{len(plans)} migrations, {len(ran)} ran, "
        f"{sum(1 for p in ran if p.safe)} fully reversible, "
        f"{len(hidden)} match on schema and lose data"
    )
    print(
        f"    of those {len(hidden)}, "
        f"{sum(1 for p in hidden if p.trip.columns_reordered)} also moved a column, "
        "which a schema-diff tool does not compare and this table now shows"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="db-surgeon",
        description="Prove a migration's rollback on a throwaway copy before trusting it.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="run up then down and compare schema and data")
    c.add_argument("--schema", required=True, help="SQL creating the starting schema")
    c.add_argument("--seed", help="SQL inserting the starting rows")
    c.add_argument("--up", required=True)
    c.add_argument("--down", required=True)
    c.add_argument("--name")
    c.add_argument("--json")
    c.add_argument("--strict", action="store_true", help="exit 1 unless fully reversible")
    c.set_defaults(func=_check_command)

    s = sub.add_parser("classify", help="read a script without running it")
    s.add_argument("sql")
    s.set_defaults(func=_classify_command)

    k = sub.add_parser("corpus", help="run the bundled migration corpus")
    k.set_defaults(func=_corpus_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
