"""Measuring what survives redaction, on real conversation.

`products/data/locomo10.json` is ten long conversations between named people who
talk to each other the way people do — which means they use short forms.
"Melanie" becomes "Mel"; "Caroline" becomes "Caro" and "Care".

Redacting the exact name is the obvious implementation and it leaves every one
of those standing. For blind scoring that is the whole ballgame: the point is
not to remove a string, it is to remove the ability to identify a person, and a
reviewer who reads "Hey Mel" knows exactly who the candidate is.

The detector here is deliberately conservative. A short form only counts as a
leak when it is used as a **vocative** — directly after a greeting or thanks —
because that is unambiguous. "Nature" shares a prefix with "Nate" and is not a
leak, and a detector that cannot tell the difference reports noise.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"
BENCHMARK = DATA / "locomo10.json"

REDACTED = "[redacted]"
MIN_PREFIX = 3

# Words that reliably precede someone's name in conversation.
_VOCATIVE = re.compile(
    r"\b(hey|hi|hello|thanks|thank you|yes|no|oh|ok|okay|bye|goodbye|hah?a)\b[ ,]+"
    r"([A-Z][a-z]{1,9})\b"
)


class BenchmarkMissingError(FileNotFoundError):
    """The conversation corpus is not on disk."""


@dataclass
class Conversation:
    speakers: tuple[str, ...]
    text: str
    turns: int


@dataclass
class Leak:
    speaker: str
    survived: str
    occurrences: int


@dataclass
class Result:
    conversation: int
    speakers: tuple[str, ...]
    exact_removed: int = 0
    leaks: list = field(default_factory=list)

    @property
    def leaked(self) -> bool:
        return bool(self.leaks)

    @property
    def leaked_names(self) -> set[str]:
        return {leak.speaker for leak in self.leaks}


@lru_cache(maxsize=1)
def conversations(path: str | None = None) -> tuple[Conversation, ...]:
    target = Path(path) if path else BENCHMARK
    if not target.exists():
        raise BenchmarkMissingError(f"{target} is missing.")
    raw = json.loads(target.read_text(encoding="utf-8"))
    out: list[Conversation] = []
    for sample in raw:
        block = sample.get("conversation", {})
        turns = [
            turn
            for key in block
            if key.startswith("session_") and not key.endswith("date_time")
            for turn in block.get(key, [])
        ]
        speakers = tuple(n for n in (block.get("speaker_a"), block.get("speaker_b")) if n)
        out.append(
            Conversation(
                speakers=speakers,
                text=" ".join(t.get("text", "") for t in turns),
                turns=len(turns),
            )
        )
    return tuple(out)


def redact_exact(text: str, names: tuple[str, ...]) -> tuple[str, int]:
    """Remove whole-word occurrences of each name. The obvious implementation."""
    removed = 0
    out = text
    for name in names:
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
        out, n = pattern.subn(REDACTED, out)
        removed += n
    return out, removed


_CAPITALISED = re.compile(r"\b([A-Z][a-z]{1,9})\b")


def _behaves_like_a_name(token: str, text: str) -> bool:
    """A word that never appears lower case in this text is a name, not a noun.

    ``Nature`` shares a prefix with ``Nate`` and appears as ``nature`` all over
    an ordinary conversation. ``Mel`` never does. That asymmetry separates the
    two without a dictionary, and without hand-listing diminutives.
    """
    return not re.search(rf"\b{re.escape(token.lower())}\b", text)


def survivors(text: str, names: tuple[str, ...], vocative_only: bool = False) -> list[Leak]:
    """Short forms that survived exact redaction.

    Two detectors, both conservative. A candidate must share at least three
    characters with a name and be shorter than it, and then either be used as a
    vocative — unambiguous — or behave like a name rather than a common word.
    """
    found: dict[tuple[str, str], int] = {}

    def consider(candidate: str) -> None:
        for name in names:
            if candidate.lower() == name.lower() or len(candidate) >= len(name):
                continue
            if candidate[:MIN_PREFIX].lower() != name[:MIN_PREFIX].lower():
                continue
            key = (name, candidate)
            found[key] = found.get(key, 0) + 1

    for match in _VOCATIVE.finditer(text):
        consider(match.group(2))

    if not vocative_only:
        for match in _CAPITALISED.finditer(text):
            token = match.group(1)
            if _behaves_like_a_name(token, text):
                consider(token)

    return [Leak(name, short, n) for (name, short), n in sorted(found.items())]


def audit(path: str | None = None) -> list[Result]:
    """Redact every conversation the obvious way, then look for who survived."""
    out: list[Result] = []
    for index, conversation in enumerate(conversations(path)):
        redacted, removed = redact_exact(conversation.text, conversation.speakers)
        out.append(
            Result(
                conversation=index,
                speakers=conversation.speakers,
                exact_removed=removed,
                leaks=survivors(redacted, conversation.speakers),
            )
        )
    return out


def leak_rate(path: str | None = None) -> float:
    """Share of conversations where a person remains identifiable after redaction."""
    results = audit(path)
    return sum(1 for r in results if r.leaked) / len(results) if results else 0.0
