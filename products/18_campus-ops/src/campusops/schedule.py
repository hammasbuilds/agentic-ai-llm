"""Real scheduled events, and the three ways a schedule contradicts itself.

`products/data/synthea_csv.zip` holds 5,571 real scheduled encounters with a
start, a stop, a provider, an organisation and a patient. That is structurally
a timetable: a resource, a person delivering, a person receiving, and a span.

A university timetable clashes in three ways — room, teacher, cohort. A clinic
schedule clashes in the same three — organisation, provider, patient. The
mapping is exact, which is why this corpus can answer the question a published
timetable dataset would have answered, using data that is real rather than
constructed.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .domain import COHORT, ROOM, TEACHER, Clash, Session

DATA = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA / "synthea_csv.zip"


class ScheduleMissingError(FileNotFoundError):
    """The encounter data is not on disk."""


@dataclass(frozen=True)
class Booking:
    id: str
    start: datetime
    stop: datetime
    room: str  # organisation
    teacher: str  # provider
    cohort: str  # patient

    @property
    def day(self) -> str:
        return self.start.date().isoformat()

    @property
    def minutes(self) -> tuple[int, int]:
        base = self.start.replace(hour=0, minute=0, second=0, microsecond=0)
        return (
            int((self.start - base).total_seconds() // 60),
            max(
                int((self.stop - base).total_seconds() // 60),
                int((self.start - base).total_seconds() // 60) + 1,
            ),
        )

    def as_session(self) -> Session:
        start, end = self.minutes
        return Session(self.id, self.day, start, end, self.room, self.teacher, self.cohort)


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def bookings(archive: str | None = None) -> tuple[Booking, ...]:
    path = Path(archive) if archive else ARCHIVE
    if not path.exists():
        raise ScheduleMissingError(f"{path} is missing. Fetch Synthea's published sample.")
    out: list[Booking] = []
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("encounters.csv"))
        with zf.open(name) as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
                start, stop = _parse(row["START"]), _parse(row["STOP"])
                if start is None or stop is None or stop < start:
                    continue
                out.append(
                    Booking(
                        id=row["Id"],
                        start=start,
                        stop=stop,
                        room=row["ORGANIZATION"],
                        teacher=row["PROVIDER"],
                        cohort=row["PATIENT"],
                    )
                )
    return tuple(out)


def sessions(archive: str | None = None) -> list[Session]:
    return [b.as_session() for b in bookings(archive)]


def clashes_by_day(archive: str | None = None) -> dict[str, list[Clash]]:
    """Clashes, computed per day.

    Per day because comparing every booking against every other across a
    multi-year corpus is quadratic in 5,571 and answers a question nobody asked:
    two appointments a year apart do not clash.
    """
    from .domain import clashes as find

    grouped: dict[str, list[Session]] = defaultdict(list)
    for session in sessions(archive):
        grouped[session.day].append(session)
    return {day: find(rows) for day, rows in grouped.items() if len(rows) > 1}


@dataclass(frozen=True)
class Report:
    days: int
    bookings: int
    clashing_days: int
    by_dimension: dict

    @property
    def total(self) -> int:
        return sum(self.by_dimension.values())

    @property
    def clean_days(self) -> float:
        return 1 - (self.clashing_days / self.days) if self.days else 1.0


def report(archive: str | None = None) -> Report:
    found = clashes_by_day(archive)
    counts: dict[str, int] = defaultdict(int)
    clashing = 0
    for day_clashes in found.values():
        if day_clashes:
            clashing += 1
        for clash in day_clashes:
            counts[clash.dimension] += 1
    days = len({b.day for b in bookings(archive)})
    return Report(
        days=days,
        bookings=len(bookings(archive)),
        clashing_days=clashing,
        by_dimension={k: counts.get(k, 0) for k in (ROOM, TEACHER, COHORT)},
    )
