"""A human baseline for how much two renderings of the same content overlap.

This product's claim is that per-platform "voice adaptation" produces four
near-identical texts. Testing that needs a yardstick: how different *are* two
genuine renderings of one thing, when different people write them?

`products/data/ami_manual.zip` answers it. Each AMI meeting carries up to four
participant summaries — the same meeting, written up separately by each person
who was in it. Same content, same facts, four independent renderings, by humans
with no instruction to differ.

That is the number a platform adapter should be compared against. Overlap far
above it is not adaptation, it is reformatting.

The user's own posts are what this product will eventually measure. This is the
baseline that makes that measurement mean something, and it is available now.
"""

from __future__ import annotations

import random
import re
import statistics
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree as ET

from .domain import content_tokens

DATA = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA / "ami_manual.zip"

_NAME = re.compile(r"^(?P<meeting>[A-Za-z0-9]+)\.(?P<who>[A-Z])\.summ\.xml$")


class CorpusMissingError(FileNotFoundError):
    """The AMI summaries are not on disk."""


@dataclass(frozen=True)
class Rendering:
    meeting: str
    author: str
    text: str

    @property
    def tokens(self) -> set[str]:
        return set(content_tokens(self.text))


def overlap(a: Rendering, b: Rendering) -> float:
    """Share of the shorter rendering's content words present in the longer.

    Containment rather than Jaccard, matching `domain.overlap`: the question is
    how much of one text is already in the other, and a shorter text should not
    be rewarded for brevity.
    """
    ta, tb = a.tokens, b.tokens
    if not ta or not tb:
        return 0.0
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & large) / len(small)


@lru_cache(maxsize=1)
def renderings(archive: str | None = None) -> tuple[Rendering, ...]:
    path = Path(archive) if archive else ARCHIVE
    if not path.exists():
        raise CorpusMissingError(f"{path} is missing. Fetch the AMI manual annotations.")
    out: list[Rendering] = []
    with zipfile.ZipFile(path) as zf:
        for member in sorted(zf.namelist()):
            if not member.startswith("participantSummaries/"):
                continue
            match = _NAME.match(member.split("/")[-1])
            if not match:
                continue
            try:
                root = ET.fromstring(zf.read(member))
            except ET.ParseError:
                continue
            text = " ".join((node.text or "").strip() for node in root.iter("sent")).strip()
            if len(text.split()) >= 30:
                out.append(Rendering(match.group("meeting"), match.group("who"), text))
    return tuple(out)


def by_meeting(archive: str | None = None) -> dict[str, list[Rendering]]:
    grouped: dict[str, list[Rendering]] = defaultdict(list)
    for rendering in renderings(archive):
        grouped[rendering.meeting].append(rendering)
    return {k: v for k, v in grouped.items() if len(v) > 1}


@dataclass(frozen=True)
class Baseline:
    meetings: int
    same_pairs: int
    different_pairs: int
    same_median: float
    different_median: float

    @property
    def separation(self) -> float:
        """How much more two renderings of one meeting share than of two."""
        return self.same_median - self.different_median


def _pairs(archive: str | None = None) -> tuple[list[float], list[float]]:
    """Same-meeting overlaps, and the different-meeting control.

    The control used to stop at the first 40 meetings, for no reason the code
    gave — all 80 cost 3,160 comparisons, which is nothing. Taking every one
    moves the control median from 0.1591 to 0.1556.
    """
    grouped = by_meeting(archive)
    same: list[float] = []
    for rows in grouped.values():
        same.extend(overlap(a, b) for a, b in combinations(rows, 2))

    # The control: renderings of different meetings, which share only the
    # vocabulary of people describing a meeting.
    flat = [rows[0] for rows in grouped.values()]
    different = [overlap(a, b) for a, b in combinations(flat, 2)]
    return same, different


def baseline(archive: str | None = None) -> Baseline:
    """Overlap within a meeting, against overlap across meetings."""
    grouped = by_meeting(archive)
    same, different = _pairs(archive)

    return Baseline(
        meetings=len(grouped),
        same_pairs=len(same),
        different_pairs=len(different),
        same_median=statistics.median(same) if same else 0.0,
        different_median=statistics.median(different) if different else 0.0,
    )


@dataclass(frozen=True)
class Significance:
    """Is the separation real, or the size of the gap two medians wander by?"""

    separation: float
    p_value: float
    low: float  # 95% bootstrap interval on the separation
    high: float

    @property
    def real(self) -> bool:
        return self.p_value < 0.01 and self.low > 0


def separation_significance(
    archive: str | None = None, trials: int = 10_000, seed: int = 7
) -> Significance:
    """Permutation test and bootstrap interval on the same-vs-different gap.

    The separation is 0.073, which is small enough that reporting it as a fact
    without testing it would be a guess. Two people describing one meeting
    overlap at 0.229; two people describing *different* meetings overlap at
    0.156, purely from the vocabulary of describing a meeting at all. Seven
    points is the entire signal, and the product's argument rests on it.

    It holds: 0 of 10,000 label shuffles reach the observed gap, and the 95%
    bootstrap interval is [0.060, 0.085] — small, and nowhere near zero.

    Seeded, so the figure in the README is the figure a reader reproduces.
    """
    same, different = _pairs(archive)
    if not same or not different:
        return Significance(0.0, 1.0, 0.0, 0.0)

    observed = statistics.median(same) - statistics.median(different)
    rng = random.Random(seed)

    pool = same + different
    n = len(same)
    hits = 0
    for _ in range(trials):
        rng.shuffle(pool)
        if statistics.median(pool[:n]) - statistics.median(pool[n:]) >= observed:
            hits += 1

    boots = sorted(
        statistics.median([rng.choice(same) for _ in range(n)])
        - statistics.median([rng.choice(different) for _ in range(len(different))])
        for _ in range(2_000)
    )
    return Significance(observed, hits / trials, boots[50], boots[-50])
