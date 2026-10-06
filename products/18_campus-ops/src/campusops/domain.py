"""Does this timetable clash with itself.

Three ways, not one. The first version of this checked rooms and published a
timetable in which a lecturer taught two classes simultaneously.
"""

from __future__ import annotations

from dataclasses import dataclass

ROOM = "room"
TEACHER = "teacher"
COHORT = "cohort"
DIMENSIONS = (ROOM, TEACHER, COHORT)


@dataclass(frozen=True)
class Session:
    id: str
    day: str
    start: int  # minutes from midnight
    end: int
    room: str
    teacher: str
    cohort: str

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"session {self.id} ends before it begins")

    def overlaps(self, other: Session) -> bool:
        """Half-open. A session ending at 10:00 does not clash with one starting then."""
        if self.day != other.day:
            return False
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Clash:
    dimension: str
    value: str
    first: str
    second: str


def clashes(sessions: list[Session]) -> list[Clash]:
    """Every way this timetable contradicts itself, in a stable order."""
    ordered = sorted(sessions, key=lambda s: (s.day, s.start, s.id))
    found: list[Clash] = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            if not first.overlaps(second):
                continue
            for dimension in DIMENSIONS:
                if getattr(first, dimension) == getattr(second, dimension):
                    found.append(
                        Clash(dimension, getattr(first, dimension), first.id, second.id)
                    )
    return found


def publishable(sessions: list[Session]) -> bool:
    """A timetable with a clash is not published. There is no warning state."""
    return not clashes(sessions)


def utilisation(sessions: list[Session], room: str, minutes_available: int) -> float:
    """Share of a room's available minutes that are booked."""
    if minutes_available <= 0:
        raise ValueError("a room with no available minutes has no utilisation")
    booked = sum(s.end - s.start for s in sessions if s.room == room)
    return booked / minutes_available


def clash_rate(before: list[Session], after: list[Session]) -> float:
    """Reduction in clashes. The number a registrar cares about."""
    first = len(clashes(before))
    if first == 0:
        return 0.0
    return 1 - (len(clashes(after)) / first)
