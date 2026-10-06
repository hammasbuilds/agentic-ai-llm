"""How different are the four platform variants, really.

The product claim is per-platform adaptation. This module is what makes that
claim falsifiable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "you",
        "your",
    ]
)

_WORD = re.compile(r"[a-z0-9']+")
_TAG = re.compile(r"[#@]\w+")
_URL = re.compile(r"https?://\S+")


def content_tokens(text: str) -> list[str]:
    """Lower-cased content words. Hashtags, mentions and URLs are not content."""
    cleaned = _URL.sub(" ", _TAG.sub(" ", text.lower()))
    return [w for w in _WORD.findall(cleaned) if w not in STOP]


def hashtags(text: str) -> list[str]:
    return sorted({t.lower() for t in _TAG.findall(text) if t.startswith("#")})


def overlap(variant: str, baseline: str) -> float:
    """Share of the variant's content words that already appear in the baseline.

    Containment rather than Jaccard: the question is "did the adapter add
    anything", and a shorter variant should not be rewarded for being shorter.
    """
    a = set(content_tokens(variant))
    b = set(content_tokens(baseline))
    if not a:
        return 1.0 if not b else 0.0
    return len(a & b) / len(a)


@dataclass(frozen=True)
class VariantReport:
    platform: str
    overlap: float
    added_words: int
    hashtags: int


def compare(baseline: str, variants: dict[str, str]) -> list[VariantReport]:
    """One row per platform, ordered most-derivative first."""
    base = set(content_tokens(baseline))
    rows = [
        VariantReport(
            platform=name,
            overlap=round(overlap(text, baseline), 4),
            added_words=len(set(content_tokens(text)) - base),
            hashtags=len(hashtags(text)),
        )
        for name, text in variants.items()
    ]
    return sorted(rows, key=lambda r: (-r.overlap, r.platform))


def best_hour(published: list[tuple[int, int]]) -> int:
    """The hour with the highest mean engagement, from your own history.

    ``published`` is (hour, engagement). Ties go to the earlier hour so the
    answer does not move between runs.
    """
    if not published:
        raise ValueError("no history to compute a posting hour from")
    totals: dict[int, list[int]] = {}
    for hour, engagement in published:
        if not 0 <= hour <= 23:
            raise ValueError(f"{hour} is not an hour")
        totals.setdefault(hour, []).append(engagement)
    means = {h: sum(v) / len(v) for h, v in totals.items()}
    return min(means, key=lambda h: (-means[h], h))
