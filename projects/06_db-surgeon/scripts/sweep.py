"""Run every migration in the corpus and report what survived the round trip.

Produces the table in the README. Every figure there came from this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "migrations"))

from corpus import CASES, SCHEMA, SEED  # noqa: E402

from dbsurgeon.plan import build  # noqa: E402

rows = []
for name, up, down, belief in CASES:
    plan = build(name, SCHEMA, SEED, up, down)
    rows.append((name, plan, belief))

print(f"{'migration':36s} {'schema':>7s} {'data':>6s} {'verdict':>28s}")
print("-" * 82)
for name, plan, _ in rows:
    if plan.error:
        print(f"{name:36s} {'-':>7s} {'-':>6s} {'did not run':>28s}")
        continue
    trip = plan.trip
    print(
        f"{name:36s} {'ok' if trip.schema_restored else 'NO':>7s} "
        f"{'ok' if trip.data_restored else 'LOST':>6s} {plan.verdict:>28s}"
    )

ran = [p for _, p, _ in rows if p.trip is not None]
failed = [p for _, p, _ in rows if p.trip is None]
lossy = [p for p in ran if not p.trip.data_restored]
schema_ok_data_lost = [p for p in ran if p.trip.schema_equivalent and not p.trip.data_restored]
reordered = [p for p in ran if p.trip.columns_reordered]
fully = [p for p in ran if p.safe]

print("-" * 82)
print(f"total migrations              : {len(rows)}")
print(f"  ran                         : {len(ran)}")
print(f"  refused to run              : {len(failed)}")
print(f"  fully reversible            : {len(fully)}")
print(f"  lost data                   : {len(lossy)}")
print(f"  columns silently reordered  : {len(reordered)}")
print(
    f"  SCHEMA MATCHES, DATA LOST   : {len(schema_ok_data_lost)}"
    f"  <- invisible to a schema-only check"
)

print()
print("the ones that pass a schema check and still lose data:")
for p in schema_ok_data_lost:
    print(
        f"  - {p.name}: {', '.join(p.trip.changed_tables())} altered, "
        f"{p.trip.rows_lost} row(s) lost"
    )

disagreements = [(p.name, d) for _, p, _ in rows for d in p.disagreements]
if disagreements:
    print()
    print("static rules vs the round trip:")
    for name, line in disagreements:
        print(f"  - {name}: {line}")
