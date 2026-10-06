"""Medication state rebuilt from events, and sentences that cannot cite one.

The current-state table and the event stream disagree more often than anyone
expects. This module only ever reads the stream.
"""

from __future__ import annotations

from dataclasses import dataclass

ORDERED = "ordered"
DISCONTINUED = "discontinued"
KINDS = (ORDERED, DISCONTINUED)


@dataclass(frozen=True)
class Event:
    id: str
    seq: int
    kind: str
    drug: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.kind!r} is not one of {KINDS}")


@dataclass(frozen=True)
class Active:
    drug: str
    evidence: str


def active_medications(events: list[Event]) -> list[Active]:
    """Drugs in force at the end of the stream, each with the event that put it there.

    Re-ordering a previously discontinued drug makes it active again, which a
    set difference over the whole stream gets wrong.
    """
    state: dict[str, Event | None] = {}
    for event in sorted(events, key=lambda e: e.seq):
        state[event.drug] = event if event.kind == ORDERED else None
    return [Active(drug, ev.id) for drug, ev in sorted(state.items()) if ev is not None]


def discontinued(events: list[Event]) -> set[str]:
    """Drugs whose last event stopped them. A summary naming one is the bug."""
    live = {a.drug for a in active_medications(events)}
    return {e.drug for e in events} - live


@dataclass(frozen=True)
class Sentence:
    text: str
    cites: tuple[str, ...] = ()


@dataclass
class Draft:
    kept: list[Sentence]
    dropped: list[Sentence]

    @property
    def drop_rate(self) -> float:
        total = len(self.kept) + len(self.dropped)
        return 0.0 if total == 0 else len(self.dropped) / total


def cite_or_drop(sentences: list[Sentence], events: list[Event]) -> Draft:
    """Remove any sentence that does not cite a real event in this encounter.

    Done before a clinician sees the draft, not after. A reviewer asked to spot
    an uncited sentence in otherwise fluent prose will not spot it.
    """
    known = {e.id for e in events}
    kept: list[Sentence] = []
    dropped: list[Sentence] = []
    for sentence in sentences:
        if sentence.cites and all(c in known for c in sentence.cites):
            kept.append(sentence)
        else:
            dropped.append(sentence)
    return Draft(kept, dropped)
