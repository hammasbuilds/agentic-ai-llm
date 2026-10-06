"""The two localization prompts and the parsers for what they return.

One home, because there were two. App 01 held these inline and `retrieval.py` held a
second copy with its own wording, its own parser and its own HTTP call — and the
second copy returned an empty list when ollama did not answer, so a call that never
happened would have been scored as a ranking that found nothing. That copy is gone and
this is what is left: the prompt text, and the two parsers that read a reply.

Nothing here talks to a model. The caller does that through `apps._platform.model`,
which refuses to publish a rate from a run with a missing generation.
"""

from __future__ import annotations

import re

LOCATE_PROMPT = """You are localizing a bug in the {repo} repository.

Below is a bug report. Name the source files most likely to need editing to fix it.

Rules:
- Output ONLY file paths, one per line, most likely first.
- Use full repository-relative paths, e.g. django/db/models/query.py
- At most 10 paths. No prose, no numbering, no backticks.

BUG REPORT:
{issue}
"""

RERANK_PROMPT = """You are localizing a bug in the {repo} repository.

Below is a bug report, then a numbered list of candidate files from that repository.
Choose the 10 candidates most likely to need editing, best first.

Rules:
- Output ONLY the numbers, one per line, best first.
- Choose only from the list. Do not invent paths.

BUG REPORT:
{issue}

CANDIDATES:
{candidates}
"""


#: A path-shaped token, which is what both parsers are actually looking for. Anchored
#: so a sentence does not contribute its last word, and the extension list is closed
#: because an unanchored "has a slash in it" matches prose like "and/or".
PATH = re.compile(
    r"""
    (?:^|[\s"'`(\[*/])                        # start, or an opening delimiter
    (?P<path>
        (?:[\w.+-]+/)*                         # directories, possibly none
        [\w.+-]+
        \.(?:py|pyx|pyi|js|ts|tsx|jsx|rb|go|rs|java|c|h|cc|cpp|php|cs|scala|kt|md|rst|txt|cfg|ini|toml|yaml|yml|json)
    )
    (?::\d+(?::\d+)?)?                         # file.py:112 and file.py:112:4
    (?=$|[\s"'`)\]*,.;:!?])                    # end, or a closing delimiter
    """,
    re.VERBOSE,
)


#: "[label](target)" - the target is the answer, the label is decoration.
_MD_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")


def _paths_in(line: str) -> list[str]:
    """Every path-shaped token in one line of a reply, in order.

    A reply does not arrive as bare paths however firmly the prompt asks. Across the
    shapes a model actually produces - `**lib/matplotlib/widgets.py**`,
    `"django/db/models/query.py"`, `sympy/core/mul.py:112`, a markdown link, a path
    followed by " - the handler" - the old parser stripped backticks and nothing else,
    then required the whole line to be a path with no space in it. So a bolded path
    kept its asterisks, a quoted one its quotes, a cited one its line number, and each
    went on to be counted as a named path that does not exist in the repository.

    That is the worst possible failure mode for this measurement: the arm is charged
    with inventing a file when what happened is that the harness could not read its
    answer. A dropped line is a miss for recall, which is visible; a mangled line is a
    fabrication, which reads as a claim about the model.
    """
    # A markdown link is the one shape that holds two path-shaped tokens where only
    # one is an answer: "[query.py](django/db/models/query.py)" named a single file,
    # and reading the label as well as the target adds a bare "query.py" that almost
    # never exists at the repository root - a fabrication invented by the parser.
    line = _MD_LINK.sub(r"\1", line)
    return [m.group("path") for m in PATH.finditer(line)]


def parse_paths(text: str, k: int = 10) -> list[str]:
    """The paths a model named, in its own order.

    One path per line is what the prompt asks for and roughly what arrives, so the
    line order is kept; within a line, a path cited as prose ("the fix belongs in
    sympy/core/mul.py, near line 112") is read rather than discarded. Fenced-block
    markers, a language tag and a bare prose line contribute nothing because nothing
    in them is path-shaped.

    `./` is stripped, and so is a leading `/`: an absolute-looking answer is a prefix
    convention, not a different file, and `resolve` in `evaluate.py` is what reconciles
    the rest.
    """
    paths: list[str] = []
    for raw in (text or "").splitlines():
        for found in _paths_in(raw):
            path = found.lstrip("./").lstrip("/")
            if path and path not in paths:
                paths.append(path)
            if len(paths) >= k:
                return paths
    return paths


def dropped_lines(text: str) -> list[str]:
    """Lines of a reply that contributed no path, minus the ones that never could.

    Fabrication is a claim about a model and a parse failure is a claim about this
    harness, so the two must not be summed. Anything this returns is a line the model
    wrote that the parser did not understand; an empty list is the only reading under
    which a fabrication rate is a statement about the model alone.
    """
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or _paths_in(raw):
            continue
        out.append(line)
    return out


#: A number that states how many, not which one. The prompt itself says "Choose the
#: 10 candidates", so a model that restates the instruction before answering wrote a
#: 10 that used to be read as a pick of candidate #10.
#:
#: These are deleted from the line and the rest of it is still read, because skipping
#: the whole line would throw away "I choose numbers 2 and 5" and "Choose the 10
#: best: 4" - both of which are answers that happen to share a line with a count.
#: A markdown list marker, where the number is the position in the list and not
#: the candidate. "1. 3" is one pick - the first choice is candidate 3 - and was
#: read as two, which put candidate 1 into the ranking ahead of the real answer.
#:
#: It only strips when something follows, so a pick written "12." keeps its number.
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+(?=\S)")

_A_COUNT = re.compile(
    r"\b(?:top|first|at most)\s+\d+"
    r"|\d+\s*(?:candidates?|files?|paths?|best|most likely)\b",
    re.IGNORECASE,
)


def parse_choices(text: str, candidates: list[str], k: int = 10) -> list[str]:
    """The candidates a reranker picked, by the numbers it answered with.

    A model that replies in prose yields nothing. Falling back to the input order
    would report the lexical ranking's score under the reranker's name, which is the
    one thing this function must not do.

    Two shapes the old version got wrong, in opposite directions. It read one number
    per line, so "3, 7, 12" - which is what a model asked for a ranked shortlist very
    often returns - was one pick instead of three, and the arm was scored on a list of
    one. And it read the first number in *any* line, so a reply that opened by
    restating the prompt ("Here are the top 10 candidates:") picked candidate #10
    before the real answer began. Out-of-range numbers are ignored rather than
    clamped: a reranker choosing from a list cannot fabricate, and clamping would
    invent a choice it did not make.
    """
    picked: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = _A_COUNT.sub(" ", _LIST_MARKER.sub("", line))
        for found in re.findall(r"\d+", line):
            index = int(found) - 1
            if 0 <= index < len(candidates) and candidates[index] not in picked:
                picked.append(candidates[index])
            if len(picked) >= k:
                return picked
    return picked
