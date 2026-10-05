"""Combine the static classification with the executed round-trip into one verdict.

Two sources of truth, deliberately kept separate:

  - `operations.classify` reads the SQL and says what it thinks will happen.
  - `shadow.round_trip` runs it and records what did happen.

Where they disagree, the round-trip wins and the disagreement is reported,
because a pattern that mispredicts is a defect in this tool and should be
visible rather than smoothed over.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .operations import LOSSY, Operation, classify_script, summarise
from .shadow import MigrationFailed, RoundTrip, round_trip


@dataclass
class Plan:
    name: str
    up_operations: list[Operation]
    down_operations: list[Operation]
    trip: RoundTrip | None
    error: str | None = None
    disagreements: list[str] = field(default_factory=list)

    @property
    def predicted_lossy(self) -> bool:
        return any(op.is_lossy for op in self.up_operations)

    @property
    def observed_lossy(self) -> bool | None:
        if self.trip is None:
            return None
        return not self.trip.data_restored

    @property
    def verdict(self) -> str:
        if self.error:
            return "did not run"
        assert self.trip is not None
        return self.trip.verdict

    @property
    def safe(self) -> bool:
        return self.trip is not None and self.trip.schema_restored and self.trip.data_restored

    def lossy_operations(self) -> list[Operation]:
        return [op for op in self.up_operations if op.is_lossy]


def build(name: str, schema: str, seed: str, up: str, down: str) -> Plan:
    """Analyse one migration pair statically, then prove it on a shadow database."""
    up_ops = classify_script(up)
    down_ops = classify_script(down)

    trip: RoundTrip | None = None
    error: str | None = None
    try:
        trip = round_trip(schema, seed, up, down)
    except MigrationFailed as exc:
        error = str(exc)

    plan = Plan(
        name=name, up_operations=up_ops, down_operations=down_ops, trip=trip, error=error
    )

    if trip is not None:
        predicted = plan.predicted_lossy
        observed = plan.observed_lossy
        if predicted and not observed:
            plan.disagreements.append(
                "predicted data loss, the round-trip restored everything - "
                "the static rule is too pessimistic here"
            )
        elif observed and not predicted:
            plan.disagreements.append(
                "no rule predicted data loss, the round-trip lost data - "
                "the static rules have a gap"
            )
    return plan


def render(plan: Plan) -> str:
    w = 78
    out = ["=" * w, f"  {plan.name}  -  {plan.verdict.upper()}", "=" * w, ""]

    if plan.error:
        out.append("  THE MIGRATION DID NOT RUN")
        out.append(f"    {plan.error}")
        out.append("")
        out.append("=" * w)
        return "\n".join(out)

    trip = plan.trip
    assert trip is not None

    out.append("  ROUND TRIP  (up, then down, on a throwaway copy)")
    out.append(f"    schema restored : {'yes' if trip.schema_restored else 'NO'}")
    out.append(f"    data restored   : {'yes' if trip.data_restored else 'NO'}")
    if not trip.data_restored:
        changed = trip.changed_tables()
        out.append(f"    tables altered  : {', '.join(changed) if changed else '-'}")
        out.append(f"    rows lost       : {trip.rows_lost}")
        out.append("")
        out.append("    The schema comparison passes and the data comparison does not.")
        out.append("    A review that checks only the schema would call this reversible.")

    out.append("")
    out.append("  UP  " + str(summarise(plan.up_operations)))
    for op in plan.up_operations:
        mark = "LOSSY" if op.is_lossy else op.category[:5]
        out.append(f"    [{mark:>5s}] {op.kind:24s} {op.target}")
        if op.category == LOSSY or op.category == "blocking":
            out.append(f"             {op.reason}")

    out.append("")
    out.append("  DOWN  " + str(summarise(plan.down_operations)))
    for op in plan.down_operations:
        out.append(f"    [{op.category[:5]:>5s}] {op.kind:24s} {op.target}")

    if plan.disagreements:
        out.append("")
        out.append("  STATIC RULES vs THE ROUND TRIP")
        for line in plan.disagreements:
            out.append(f"    {line}")

    out.append("")
    out.append("=" * w)
    return "\n".join(out)
