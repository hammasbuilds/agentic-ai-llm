"""Real documents with real mandatory requirements, and a ground truth for them.

`products/data/rfc*.txt` are published RFCs. RFC 2119 defines exactly which
words make a requirement binding, and — the part that makes this measurable —
it says they count **only when written in upper case**:

    "These words are often capitalized... they have the specific meaning
     described here only when they appear in all capitals."

So `MUST` is a requirement and `must` in the same document is prose. That gives
a labelled corpus of mandatory, advisory and optional items with no annotation
needed, in documents where missing a mandatory item really does mean rejection.

A tender is the same shape: a compliance clause is binding or it is not, and
telling the two apart by reading for the word "must" is the mistake.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"

# RFC 2119, section 1-5. Upper case only.
MANDATORY = ("MUST", "REQUIRED", "SHALL")
PROHIBITED = ("MUST NOT", "SHALL NOT")
ADVISORY = ("SHOULD", "RECOMMENDED", "SHOULD NOT", "NOT RECOMMENDED")
OPTIONAL = ("MAY", "OPTIONAL")

_STRICT = re.compile(
    r"\b(MUST NOT|SHALL NOT|SHOULD NOT|NOT RECOMMENDED|MUST|REQUIRED|SHALL|"
    r"SHOULD|RECOMMENDED|MAY|OPTIONAL)\b"
)
# What a reader looking for obligations does instead: match the word, any case.
_LOOSE = re.compile(
    r"\b(must not|shall not|should not|must|required|shall|should|"
    r"recommended|may|optional)\b",
    re.I,
)


class DocumentsMissingError(FileNotFoundError):
    """No RFC text files on disk."""


@dataclass(frozen=True)
class Requirement:
    document: str
    line: int
    keyword: str
    text: str

    @property
    def mandatory(self) -> bool:
        return self.keyword in MANDATORY or self.keyword in PROHIBITED


def _documents(root: Path | None = None) -> list[Path]:
    base = root or DATA
    found = sorted(base.glob("rfc*.txt"))
    if not found:
        raise DocumentsMissingError(f"no rfc*.txt under {base}")
    return found


@lru_cache(maxsize=1)
def strict(root: str | None = None) -> tuple[Requirement, ...]:
    """Requirements as RFC 2119 defines them: the keyword in upper case."""
    out: list[Requirement] = []
    for path in _documents(Path(root) if root else None):
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines()):
            for match in _STRICT.finditer(line):
                out.append(Requirement(path.stem, n, match.group(1), line.strip()))
    return tuple(out)


@lru_cache(maxsize=1)
def loose(root: str | None = None) -> tuple[Requirement, ...]:
    """What a case-insensitive reader finds. The naive extractor."""
    out: list[Requirement] = []
    for path in _documents(Path(root) if root else None):
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines()):
            for match in _LOOSE.finditer(line):
                out.append(Requirement(path.stem, n, match.group(1).upper(), line.strip()))
    return tuple(out)


def mandatory_only(items) -> list[Requirement]:
    return [r for r in items if r.mandatory]


@dataclass(frozen=True)
class Comparison:
    truth: int
    found: int
    overlap: int

    @property
    def recall(self) -> float:
        return self.overlap / self.truth if self.truth else 0.0

    @property
    def precision(self) -> float:
        return self.overlap / self.found if self.found else 0.0

    @property
    def false_positives(self) -> int:
        return self.found - self.overlap


def _key(r: Requirement) -> tuple[str, int, str]:
    return (r.document, r.line, r.keyword)


def compare_mandatory(root: str | None = None) -> Comparison:
    """The naive extractor against RFC 2119's own definition, on mandatory items."""
    truth = {_key(r) for r in mandatory_only(strict(root))}
    found = {_key(r) for r in mandatory_only(loose(root))}
    return Comparison(truth=len(truth), found=len(found), overlap=len(truth & found))


def by_keyword(items) -> dict[str, int]:
    return dict(Counter(r.keyword for r in items).most_common())
