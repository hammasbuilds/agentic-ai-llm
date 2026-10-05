"""Claims a sentence checker cannot see, because they are made by layout.

A heading that says "All ten, at a glance" above a table of seven rows is drift,
and no regex over sentences will find it: the number is in the heading, the
noun is nowhere, and the evidence is the table underneath.

This was not hypothetical. Pointed at a real published repository, the sentence
checker found **zero** checkable claims in a README whose own heading said
"All ten" above seven rows. The claim was there; the shape of it was wrong.

Markdown carries enough structure to settle it: a heading with a count, and the
first block beneath it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .domain import _WORD_NUMBERS

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S")
_FENCE = re.compile(r"^\s*(?:```|~~~)")

# The digits have to stand alone. Without the trailing guard, "all 3,975 pages"
# matched "3" and "qwen2.5-coder:14b" matched "5" - a count read out of the middle
# of a larger number or a model name, which is how a correct README is reported as
# drifted and how a checker loses the right to be believed.
# A comma or full stop AFTER the number is ordinary punctuation - "All ten, at a
# glance" - so only a thousands separator or a decimal point disqualifies it.
_NUMBER = re.compile(
    rf"(?<![\d.,:\-])\b(\d{{1,3}}|{'|'.join(_WORD_NUMBERS)})\b"
    rf"(?![\d:%\-]|,\d|\.\d|\s*%|[A-Za-z])",
    re.I,
)

# A number can appear in a heading without counting anything. Each of these was
# a false positive on a real README, and together they took the reported rate
# from an unbelievable 81% down to something that survives being looked at.
#
#   "04 · The injection that isn't an instruction"  -> a section index
#   "4. Consent and purpose limitation"             -> a numbered list item
#   "2026-09-16 · qwen2.5-coder:14b added"          -> a date
#   "Top 5 findings"                                -> a rank, not a count
_SECTION_INDEX = re.compile(r"^\[?\s*\d{1,2}\s*(?:[-–—·:.)\]]|\s\S)")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_VERSIONED = re.compile(r"\b[vV]?\d+\.\d+")
_RANKING = re.compile(r"\b(top|best|worst|first|last)\s+\d", re.I)
# "Result 3 - the average is carried by four trivial cases", "Finding 5 in detail",
# "Round 2". The number says WHICH section this is; the block under it is not three
# of anything.
_ORDINAL_LABEL = re.compile(
    r"^\s*(?:result|finding|round|phase|step|stage|part|chapter|section|appendix"
    r"|table|figure|fig|example|case|note|question|q|experiment|run|day|week)"
    r"\s*\.?\s*\d{1,3}\b",
    re.I,
)
# "There aren't 200 sources. There are about ten." A number being denied, bounded
# or approximated is not a number being counted.
_NEGATED = re.compile(
    r"\b(?:aren'?t|isn'?t|are\s+not|is\s+not|not|no|never|without|only"
    r"|fewer\s+than|less\s+than|more\s+than|under|over|about|around|roughly|~)"
    r"\s+(?:\w+\s+){0,2}?\d{1,3}\b",
    re.I,
)
# A measurement rather than a tally: "F1 with 95% bootstrap CI", "within 3 ms".
_MEASURE = re.compile(
    r"\d{1,3}\s*(?:%|percent|ms\b|sec\b|mins?\b|hours?\b|MB\b|GB\b|KB\b|px\b|k\b)"
    r"|\bCI\b|\bp\s*[<=>]",
    re.I,
)
#: A count labels the block and says so early - "The twenty business agents", "Ten
#: palettes". Once the number is buried mid-sentence the heading is prose about a
#: dataset: "What it scores, on 47 questions with qwen2.5-coder" counts nothing
#: beneath it, and reading it as a count is how this checker reported 81% of the
#: portfolio as broken.
_LATE_NUMBER_WORDS = 6


def _is_a_count(heading: str) -> bool:
    """Whether the number in this heading is counting the block beneath it."""
    heading = heading.strip()
    if _SECTION_INDEX.match(heading) or _ORDINAL_LABEL.match(heading):
        return False
    if _DATE.search(heading) or _VERSIONED.search(heading) or _RANKING.search(heading):
        return False
    if _NEGATED.search(heading) or _MEASURE.search(heading):
        return False
    match = _NUMBER.search(heading)
    if not match:
        return False
    before = heading[: match.start()]
    # A clause break before the number means the heading is a sentence that
    # mentions a quantity, not a label on a list: "What it scores, on 47 questions
    # with qwen2.5-coder" has nothing to do with the two items beneath it.
    if any(punctuation in before for punctuation in ",;("):
        return False
    return len(before.split()) < _LATE_NUMBER_WORDS


def _without_code(markdown: str) -> list[str]:
    """Lines outside fenced code blocks.

    A JSON line inside a fence was being read as a heading, which is how
    `{"source": "worldbank.org", "quote": "...12.4%"}` became a claim about
    twelve of something.
    """
    out: list[str] = []
    inside = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return out


@dataclass(frozen=True)
class Counted:
    """A heading that states a number, and what actually follows it."""

    heading: str
    stated: int
    found: int
    kind: str  # "table" or "list"

    @property
    def holds(self) -> bool:
        return self.stated == self.found

    @property
    def detail(self) -> str:
        return (
            f"heading says {self.stated}, the {self.kind} beneath it has {self.found}"
        )


def _stated(heading: str) -> int | None:
    match = _NUMBER.search(heading)
    if not match:
        return None
    raw = match.group(1).lower()
    return int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw)


def _cells(row: str) -> list[str]:
    """The cells of a markdown table row, trimmed and lower-cased."""
    return [c.strip().lower() for c in row.strip().strip("|").split("|")]


def _across(header: list[str]) -> int:
    """How many entities one row of this table holds.

    A wide list is often laid out in several columns to keep it readable, and
    then its header repeats: `# | Agent | # | Agent` is two entities per row.
    The repetition is the evidence, so a header that does not repeat gives 1 and
    nothing changes for an ordinary table.
    """
    labels = [c for c in header]
    width = len(labels)
    if width < 2 or any(not c for c in labels):
        return 1
    # The shortest prefix the whole header is a repetition of.
    for period in range(1, width // 2 + 1):
        if width % period:
            continue
        if all(labels[i] == labels[i % period] for i in range(width)):
            return width // period
    return 1


def _count_block(lines: list[str], start: int) -> tuple[str, int]:
    """Rows in the first table, or items in the first list, after ``start``."""
    i = start
    # Skip blank lines and prose until a table or list begins.
    while i < len(lines) and not (
        _TABLE_ROW.match(lines[i]) or _LIST_ITEM.match(lines[i])
    ):
        if _HEADING.match(lines[i]):
            return ("", 0)  # the next heading arrived first; nothing to count
        i += 1
    if i >= len(lines):
        return ("", 0)

    if _TABLE_ROW.match(lines[i]):
        header = _cells(lines[i])
        rows = 0
        seen_rule = False
        while i < len(lines) and _TABLE_ROW.match(lines[i]):
            if _TABLE_RULE.match(lines[i]):
                seen_rule = True
            elif seen_rule:
                rows += 1
            i += 1
        # A table laid out several entities across counts its entities, not its
        # rows. `| # | Agent | # | Agent |` holds twenty agents in ten rows, and
        # counting rows reported this repository's own correct README as drifted
        # - a checker whose first duty is to not cry wolf.
        return ("table", rows * _across(header))

    # A list item can run over several lines. Continuation lines are indented
    # and are neither an item nor blank, and treating one as the end of the list
    # counts a three-item list as one — which is exactly how this checker
    # reported a correct README as drifted.
    items = 0
    blanks = 0
    while i < len(lines):
        line = lines[i]
        if _LIST_ITEM.match(line):
            items += 1
            blanks = 0
        elif not line.strip():
            blanks += 1
            if blanks > 1 and items:
                break  # a blank line gap ends the list
        elif line.startswith((" ", "\t")):
            blanks = 0  # an indented continuation of the current item
        elif items:
            break  # unindented prose: the list is over
        i += 1
    return ("list", items)


def counted_headings(markdown: str, min_count: int = 3) -> list[Counted]:
    """Headings stating a number, checked against the block beneath them.

    ``min_count`` skips headings like "## 01 - the size curve", where the number
    is a section index rather than a count of anything.
    """
    lines = _without_code(markdown)
    out: list[Counted] = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match:
            continue
        heading = match.group(2)
        if not _is_a_count(heading):
            continue
        stated = _stated(heading)
        if stated is None or stated < min_count:
            continue
        kind, found = _count_block(lines, index + 1)
        if kind and found:
            out.append(Counted(match.group(2).strip(), stated, found, kind))
    return out


def broken_headings(markdown: str, min_count: int = 3) -> list[Counted]:
    return [c for c in counted_headings(markdown, min_count) if not c.holds]
