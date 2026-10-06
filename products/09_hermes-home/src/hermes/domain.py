"""Constraints that must survive a handoff.

``langgraph-lab`` project 05 measured what happens when they do not: passing
only the latest message to a handed-off specialist took safety from 100% to
20%. This module makes that a refused call rather than a line in a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Constraint:
    id: str
    predicate: str
    value: str
    hard: bool

    def __str__(self) -> str:
        mark = "hard" if self.hard else "soft"
        return f"{self.predicate}={self.value} ({mark})"


class ConstraintDroppedError(RuntimeError):
    """A handoff would have lost a constraint that cannot be lost."""


@dataclass
class Handoff:
    to: str
    message: str
    constraints: list[Constraint] = field(default_factory=list)

    @property
    def carried(self) -> set[str]:
        return {c.id for c in self.constraints}


def prepare(to: str, message: str, known: list[Constraint]) -> Handoff:
    """Build a handoff carrying every known constraint.

    Deliberately not "the relevant ones". Relevance is a judgement, and the
    judgement is what was wrong in the measured failure.
    """
    if not to:
        raise ValueError("a handoff needs a target")
    return Handoff(to=to, message=message, constraints=list(known))


def dropped(known: list[Constraint], handoff: Handoff) -> list[Constraint]:
    return [c for c in known if c.id not in handoff.carried]


def verify(known: list[Constraint], handoff: Handoff) -> list[Constraint]:
    """Refuse a handoff that loses a hard constraint; report soft losses.

    Returns the soft constraints that were dropped, so the caller can log a
    degradation rather than discovering it in an outcome.
    """
    lost = dropped(known, handoff)
    hard = [c for c in lost if c.hard]
    if hard:
        raise ConstraintDroppedError(
            "handoff to " + handoff.to + " would drop: " + ", ".join(str(c) for c in hard)
        )
    return [c for c in lost if not c.hard]


def survival(known: list[Constraint], handoffs: list[Handoff]) -> float:
    """Share of constraints still carried after a chain of handoffs.

    The headline measurement, run at 50 turns, gated against ungated.
    """
    if not known:
        return 1.0
    alive = {c.id for c in known}
    for handoff in handoffs:
        alive &= handoff.carried
    return len(alive) / len(known)
