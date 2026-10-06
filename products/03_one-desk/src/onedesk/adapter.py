"""Running a real per-platform adapter, so its output can be measured.

The human baseline in :mod:`onedesk.variants` says two people rendering the same
content independently overlap at about 0.23. Comparing that against a
hand-written example would measure the example.

So this runs the adapter for real: a local instruct model, given one source
text, asked for a LinkedIn post, an Instagram caption, an X post and a portfolio
note — the four surfaces this product manages. The overlap between what comes
back and the source is then a measurement rather than an illustration.

Results are cached to `products/data/adapter_runs.json`, because a generation on
this card costs seconds and a test suite should not.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .domain import content_tokens, overlap

DATA = Path(__file__).resolve().parents[3] / "data"
CACHE = DATA / "adapter_runs.json"

PLATFORMS = ("linkedin", "instagram", "x", "portfolio")

PROMPTS = {
    "linkedin": (
        "Rewrite the following as a LinkedIn post for a professional audience. "
        "Keep it under 120 words. Return only the post.\n\n{source}"
    ),
    "instagram": (
        "Rewrite the following as an Instagram caption. Warm and personal, "
        "under 80 words, end with two hashtags. Return only the caption.\n\n{source}"
    ),
    "x": (
        "Rewrite the following as a single post for X. Under 40 words, direct, "
        "lower case is fine. Return only the post.\n\n{source}"
    ),
    "portfolio": (
        "Rewrite the following as a short note for a personal portfolio site. "
        "Plain and factual, under 120 words. Return only the note.\n\n{source}"
    ),
}


class NoRunsError(FileNotFoundError):
    """No adapter output has been generated yet. Run scripts/run_adapter.py."""


@dataclass
class Run:
    source: str
    variants: dict = field(default_factory=dict)
    model: str = ""

    @property
    def overlaps(self) -> dict:
        """Containment of each variant's content words in the source."""
        return {name: overlap(text, self.source) for name, text in self.variants.items()}

    @property
    def cross(self) -> list:
        """Overlap between the variants themselves, pairwise."""
        names = sorted(self.variants)
        return [
            overlap(self.variants[a], self.variants[b])
            for i, a in enumerate(names)
            for b in names[i + 1 :]
        ]

    @property
    def usable(self) -> bool:
        return len(self.variants) == len(PLATFORMS) and all(
            len(content_tokens(t)) >= 10 for t in self.variants.values()
        )


def load(path: str | None = None) -> list[Run]:
    target = Path(path) if path else CACHE
    if not target.exists():
        raise NoRunsError(
            f"{target} is missing. Generate it with: python scripts/run_adapter.py"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    return [
        Run(source=r["source"], variants=r["variants"], model=r.get("model", ""))
        for r in payload.get("runs", [])
    ]


@dataclass(frozen=True)
class Measured:
    runs: int
    model: str
    to_source_median: float
    cross_variant_median: float
    samples: int

    def versus(self, human_baseline: float) -> float:
        """How many times more derivative the adapter is than two people."""
        return self.to_source_median / human_baseline if human_baseline else 0.0


def measure(path: str | None = None) -> Measured:
    runs = [r for r in load(path) if r.usable]
    if not runs:
        raise NoRunsError("no usable adapter runs")
    to_source = [v for r in runs for v in r.overlaps.values()]
    cross = [v for r in runs for v in r.cross]
    return Measured(
        runs=len(runs),
        model=runs[0].model,
        to_source_median=statistics.median(to_source),
        cross_variant_median=statistics.median(cross) if cross else 0.0,
        samples=len(to_source),
    )
