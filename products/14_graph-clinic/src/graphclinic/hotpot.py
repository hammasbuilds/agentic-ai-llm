"""HotpotQA as a graph, and the honest baseline to judge it against.

The HuggingFace cache on this machine holds HotpotQA's distractor split: 7,405
questions, each with two gold paragraphs hidden among ten, and each labelled
``bridge`` (you must hop from one paragraph to another) or ``comparison`` (you
must read two and compare).

The graph is not invented. A paragraph titled "Scott Derrickson" that mentions
"Ed Wood" in its text is a real edge between two real entities, which is exactly
what a knowledge graph built from a corpus consists of. Whether traversing it
beats simply retrieving on the question text is the thing to measure, and given
what `rag-lab` found — six of eight clever variants lost to a plain hybrid
baseline — the honest prior is that it does not.
"""

from __future__ import annotations

import glob
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


#: Where HotpotQA is read from. This was `Path.home() / ".cache/huggingface/..."`, which
#: ignores the environment entirely - so `scripts/test_all.py --fresh`, whose whole
#: purpose is to run every suite as a reader without the data would, pointed `HF_HOME`
#: at an empty directory and this module went on reading the real cache. All 28 tests
#: ran in a sweep whose recorded counts are published as a fresh clone's.
#:
#: `apps/_engine/hf_cache.py` already fixed this shape for the hub cache, where three
#: duplicate resolvers each appended the default UNDERNEATH the overrides. This is the
#: datasets cache and was missed, and the same rule applies: an override replaces the
#: default, never adds to it.
def _datasets_cache() -> Path:
    import os  # noqa: PLC0415

    if env := os.environ.get("HF_DATASETS_CACHE"):
        return Path(env)
    if env := os.environ.get("HF_HOME"):
        return Path(env) / "datasets"
    return Path.home() / ".cache" / "huggingface" / "datasets"


CACHE = _datasets_cache() / "hotpotqa___hotpot_qa"
_WORD = re.compile(r"[a-z0-9']+")

STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    ]
)


class DatasetMissingError(FileNotFoundError):
    """HotpotQA is not in the local HuggingFace cache."""


@dataclass(frozen=True)
class Item:
    id: str
    question: str
    answer: str
    kind: str  # "bridge" or "comparison"
    level: str
    gold: tuple[str, ...]
    paragraphs: dict = field(default_factory=dict)  # title -> text

    @property
    def titles(self) -> tuple[str, ...]:
        return tuple(self.paragraphs)

    @property
    def gold_present(self) -> bool:
        return all(g in self.paragraphs for g in self.gold)


def _validation_file() -> Path:
    found = glob.glob(str(CACHE / "distractor/*/*/hotpot_qa-validation.arrow"))
    if not found:
        raise DatasetMissingError(
            f"no hotpot_qa-validation.arrow under {CACHE}. "
            "It is loaded from the local HuggingFace cache, never downloaded here."
        )
    return Path(found[0])


@lru_cache(maxsize=1)
def load(limit: int = 0) -> tuple[Item, ...]:
    """The validation split, as items with their paragraphs attached."""
    try:
        import pyarrow as pa  # noqa: PLC0415 — optional extra
    except ImportError as exc:  # pragma: no cover
        raise DatasetMissingError("pyarrow is needed to read the cache") from exc

    path = _validation_file()
    with pa.memory_map(str(path)) as src:
        table = pa.ipc.open_stream(src).read_all()

    out: list[Item] = []
    n = table.num_rows if not limit else min(limit, table.num_rows)
    ids = table.column("id")
    questions = table.column("question")
    answers = table.column("answer")
    kinds = table.column("type")
    levels = table.column("level")
    facts = table.column("supporting_facts")
    contexts = table.column("context")

    for i in range(n):
        context = contexts[i].as_py()
        titles = context["title"]
        sentences = context["sentences"]
        paragraphs = {t: " ".join(s) for t, s in zip(titles, sentences, strict=False)}
        out.append(
            Item(
                id=ids[i].as_py(),
                question=questions[i].as_py(),
                answer=answers[i].as_py(),
                kind=kinds[i].as_py(),
                level=levels[i].as_py(),
                gold=tuple(dict.fromkeys(facts[i].as_py()["title"])),
                paragraphs=paragraphs,
            )
        )
    return tuple(out)


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def mentions(item: Item) -> set[tuple[str, str]]:
    """Edges: paragraph A mentions the title of paragraph B.

    Case-insensitive substring match on the title, which is how a corpus-built
    entity graph is actually assembled. It is generous — that matters, because a
    generous graph is the strongest version of the argument being tested.
    """
    edges: set[tuple[str, str]] = set()
    lowered = {t: text.lower() for t, text in item.paragraphs.items()}
    for source, text in lowered.items():
        for target in item.paragraphs:
            if target != source and target.lower() in text:
                edges.add((source, target))
    return edges


def connected(item: Item, max_hops: int = 2) -> bool:
    """Is the second gold paragraph reachable from the first, through mentions."""
    if len(item.gold) < 2 or not item.gold_present:
        return False
    adjacency: dict[str, set[str]] = {}
    for a, b in mentions(item):
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    start, target = item.gold[0], item.gold[1]
    frontier = {start}
    seen = {start}
    for _ in range(max_hops):
        nxt: set[str] = set()
        for node in frontier:
            for neighbour in adjacency.get(node, ()):
                if neighbour == target:
                    return True
                if neighbour not in seen:
                    seen.add(neighbour)
                    nxt.add(neighbour)
        frontier = nxt
    return False


def lexical_top2(item: Item) -> tuple[str, ...]:
    """The plain baseline: rank paragraphs by word overlap with the question."""
    q = tokens(item.question)
    scored = sorted(
        item.paragraphs,
        key=lambda t: (-len(q & tokens(t + " " + item.paragraphs[t])), t),
    )
    return tuple(scored[:2])


def baseline_hits_both(item: Item) -> bool:
    return set(item.gold) <= set(lexical_top2(item))
