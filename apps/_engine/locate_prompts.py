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


def parse_paths(text: str, k: int = 10) -> list[str]:
    """The paths a model named, in its own order.

    Order matters inside the loop: strip the list marker first, then the backticks.
    Done the other way round, "1. `path`" keeps its opening backtick because the line
    starts with a digit, and every such path is then scored as a miss.
    """
    paths: list[str] = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*[-*\d.)\s]+", "", line.strip()).strip("`").strip()
        if not line or " " in line or ("/" not in line and not line.endswith(".py")):
            continue
        line = line.lstrip("./")
        if line not in paths:
            paths.append(line)
        if len(paths) >= k:
            break
    return paths


def parse_choices(text: str, candidates: list[str], k: int = 10) -> list[str]:
    """The candidates a reranker picked, by the numbers it answered with.

    A model that replies in prose yields nothing. Falling back to the input order
    would report the lexical ranking's score under the reranker's name, which is the
    one thing this function must not do.
    """
    picked: list[str] = []
    for line in text.splitlines():
        found = re.search(r"\d+", line)
        if not found:
            continue
        index = int(found.group()) - 1
        if 0 <= index < len(candidates) and candidates[index] not in picked:
            picked.append(candidates[index])
        if len(picked) >= k:
            break
    return picked
