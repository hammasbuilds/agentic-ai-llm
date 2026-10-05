"""Split a legal document into clauses, keeping every character offset.

Offsets are the whole point. A finding that says "this licence requires
attribution" is an opinion; a finding that says "characters 412-509 of
LICENSE say so, and here they are" is checkable. Every claim this package
makes carries the span it came from, and a claim whose span cannot be located
in the source is dropped rather than reported.

That rule is inherited from `rag-forge`, where a quote that could not be found
in the source was treated as a hallucination signal rather than an
inconvenience.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Numbered clauses, lettered sub-clauses, and ALL-CAPS headings are the three
# structures that actually appear in the corpus.
_HEADING = re.compile(
    r"^\s*(?:"
    r"(?P<num>\d+(?:\.\d+)*)\s*[.)]?\s+(?P<numtitle>[A-Z][^\n]{0,80})"
    r"|(?P<caps>[A-Z][A-Z \t,'\"/&()-]{8,80})"
    r"|(?P<sec>(?:Section|Article|Clause)\s+\d+[^\n]{0,60})"
    r")\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Clause:
    """A span of the document, located exactly."""

    index: int
    heading: str
    text: str
    start: int
    end: int

    @property
    def words(self) -> int:
        return len(self.text.split())

    def quote(self, start: int, end: int) -> str:
        """Text at absolute offsets, for a citation inside this clause."""
        return self.text[start - self.start : end - self.start]


def normalise(text: str) -> str:
    """Collapse the line wrapping licences use, keeping paragraph breaks.

    Licence files are hard-wrapped at 70-80 columns, so a sentence spans
    several lines and no phrase pattern matches across the break. Joining
    within paragraphs fixes that; joining across them would merge clauses.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n", text)
    joined = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.split("\n")]
        if len(lines) > 1 and all(len(line) < 100 for line in lines if line):
            joined.append(" ".join(line for line in lines if line))
        else:
            joined.append("\n".join(lines))
    return "\n\n".join(joined)


def segment(text: str) -> list[Clause]:
    """Split into clauses. A document with no headings is one clause.

    Returning the whole document as a single clause is correct for MIT, which
    has no numbered sections at all - inventing structure for it would make
    citations point at boundaries that do not exist.
    """
    matches = list(_HEADING.finditer(text))
    if not matches:
        stripped = text.strip()
        if not stripped:
            return []
        start = text.index(stripped[0]) if stripped else 0
        return [Clause(0, "(whole document)", stripped, start, start + len(stripped))]

    clauses: list[Clause] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        clauses.append(Clause(0, "(preamble)", preamble, 0, len(preamble)))

    for i, match in enumerate(matches):
        heading = (
            match.group("numtitle") or match.group("caps") or match.group("sec") or ""
        ).strip()
        number = match.group("num")
        if number:
            heading = f"{number}. {heading}"
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        offset = text.index(body[0], body_start) if body else body_start
        clauses.append(
            Clause(
                index=len(clauses),
                heading=heading or f"clause {i + 1}",
                text=body,
                start=offset,
                end=offset + len(body),
            )
        )
    return clauses


def locate(text: str, phrase: str) -> tuple[int, int] | None:
    """Find a phrase in the source, tolerant of whitespace differences.

    Returns absolute offsets, or None. None means the claim cannot be
    grounded, and an ungrounded claim is discarded.
    """
    if not phrase:
        return None
    direct = text.find(phrase)
    if direct != -1:
        return direct, direct + len(phrase)

    pattern = re.compile(r"\s+".join(re.escape(w) for w in phrase.split()), re.IGNORECASE)
    match = pattern.search(text)
    return (match.start(), match.end()) if match else None


def locate_all(text: str, phrase: str, limit: int = 12):
    """Every place the phrase appears, tolerant of whitespace differences.

    `locate` returns the first occurrence, and that is wrong for deciding whether a
    licence *adopts* a name or merely mentions it. The Creative Commons licences open
    with "Creative Commons Corporation ... is not a law firm and does not provide legal
    services" - so the first occurrence of "creative commons" sits in a sentence
    carrying two of the context disqualifiers, and reading only that one made every
    CC-licensed file unidentifiable.
    """
    if not phrase:
        return
    pattern = re.compile(r"\s+".join(re.escape(w) for w in phrase.split()), re.IGNORECASE)
    for found, match in enumerate(pattern.finditer(text)):
        if found >= limit:
            return
        yield match.start(), match.end()
