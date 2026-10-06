"""Real versioned regulation, and the question a retriever gets wrong.

`products/data/ecfr_title*.json` are eCFR version indexes for six CFR titles
— Banks, Food & Drugs, Internal Revenue, Labor, Environment, Public Welfare
— 1,000 real section versions each, every one carrying the date its
amendment took effect. Sections are amended repeatedly, so a section has a
*history*, and "which text was in force on date D" has a definite answer.

Six regulators rather than one because one regulator is one drafting
culture. Title 29 alone put the median staleness at 0.28 years; the other
five range from 1.99 to 4.35, so reading only Labor produced a fact about
OSHA dressed as a fact about versioned documents.

That is structurally the same problem as an insurance policy wording, and it is
the one this product exists to get right. A retriever that returns the current
text of a section answers a different question from the one asked about a loss
that happened four years ago — fluently, citing a real section, and wrong.

Regulation stands in for policy wordings because insurers do not publish a
machine-readable archive of superseded wordings, and inventing one would make
the measurement worthless.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"
TITLES = (12, 21, 26, 29, 40, 45)
INDEX = DATA / "ecfr_title29.json"


class IndexMissingError(FileNotFoundError):
    """The eCFR version index is not on disk."""


@dataclass(frozen=True)
class Version:
    identifier: str  # the section, e.g. "1910.1200"
    effective: date
    name: str
    removed: bool
    substantive: bool
    title: int = 29  # the CFR title it belongs to

    @property
    def section(self) -> str:
        """The section, qualified by its title.

        A bare section number is not unique across the CFR: `1.1` exists in
        five of the six titles read here, and 140 identifiers appear in more
        than one of them. Keying a history on the bare number splices
        unrelated sections together and **invents amendments** — the corpus
        would report that a section changed on a date when in truth a different
        agency's differently-numbered rule changed.
        """
        return f"{self.title}:{self.identifier}"


def _parse(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _read_one(target: Path, title: int) -> list[Version]:
    if not target.exists():
        raise IndexMissingError(f"{target} is missing. Fetch the eCFR version index.")
    payload = json.loads(target.read_text(encoding="utf-8"))
    out: list[Version] = []
    for row in payload.get("content_versions", []):
        effective = _parse(row.get("amendment_date") or row.get("date"))
        identifier = row.get("identifier")
        if effective is None or not identifier:
            continue
        out.append(
            Version(
                identifier=identifier,
                effective=effective,
                name=row.get("name", ""),
                removed=bool(row.get("removed")),
                substantive=bool(row.get("substantive")),
                title=title,
            )
        )
    return out


@lru_cache(maxsize=8)
def versions(path: str | None = None) -> tuple[Version, ...]:
    """Every section version across all six titles, or one file if named.

    Six titles rather than one because a single regulator is a single drafting
    culture. Title 29 (Labor) amends at its own pace; reading only it makes the
    rate a fact about OSHA rather than about versioned documents. The six span
    banking, food and drugs, tax, labor, environment and health.
    """
    if path:
        return tuple(_read_one(Path(path), _title_of(Path(path))))
    out: list[Version] = []
    for title in TITLES:
        out.extend(_read_one(DATA / f"ecfr_title{title}.json", title))
    return tuple(out)


def _title_of(target: Path) -> int:
    stem = target.stem
    digits = "".join(c for c in stem.split("title")[-1] if c.isdigit())
    return int(digits) if digits else 0


@lru_cache(maxsize=8)
def history(path: str | None = None) -> dict[str, list[Version]]:
    """Section -> its versions, oldest first."""
    out: dict[str, list[Version]] = defaultdict(list)
    for version in versions(path):
        out[version.section].append(version)
    return {k: sorted(v, key=lambda x: x.effective) for k, v in out.items()}


def amended(path: str | None = None) -> dict[str, list[Version]]:
    """Only the sections that were actually amended more than once."""
    return {k: v for k, v in history(path).items() if len(v) > 1}


def in_force(section: str, on: date, path: str | None = None) -> Version | None:
    """The version in force on a date. The correct answer."""
    rows = history(path).get(section)
    if not rows:
        return None
    dates = [r.effective for r in rows]
    index = bisect_right(dates, on) - 1
    return rows[index] if index >= 0 else None


def latest(section: str, path: str | None = None) -> Version | None:
    """The current version. What a retriever returns when nobody asked it not to."""
    rows = history(path).get(section)
    return rows[-1] if rows else None


@dataclass(frozen=True)
class Mismatch:
    section: str
    asked_on: date
    correct: date
    returned: date

    @property
    def years_out(self) -> float:
        return (self.returned - self.correct).days / 365.25


def wrong_version_rate(path: str | None = None) -> tuple[float, list[Mismatch]]:
    """How often "return the current text" answers the wrong question.

    Asked once per (amended section, each date its own history makes
    meaningful) — that is, for every version of every amended section, ask what
    was in force the day it took effect.
    """
    mismatches: list[Mismatch] = []
    asked = 0
    for section, rows in amended(path).items():
        newest = rows[-1]
        for row in rows:
            asked += 1
            correct = in_force(section, row.effective, path)
            if correct and correct.effective != newest.effective:
                mismatches.append(
                    Mismatch(section, row.effective, correct.effective, newest.effective)
                )
    return (len(mismatches) / asked if asked else 0.0), mismatches
