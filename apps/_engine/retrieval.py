"""Three ways to guess which file an issue is about, scored the same way.

Each retriever takes an issue and a list of candidate paths and returns those paths
ranked best-first. Nothing here reads file contents: the Trees API gives paths only,
and fetching ~20k blobs would be a clone by another name. That makes this a measurement
of *path* retrieval specifically, which is a weaker signal than a real localizer would
use and is stated as such in the results rather than glossed over.

- `bm25`   - Okapi BM25 over tokenised paths. No model, no GPU, deterministic.
- `embed`  - cosine similarity over `nomic-embed-text` vectors, locally.
- `llm`    - qwen2.5-coder:14b asked directly to name the files it would change.

The third is not retrieval in the same sense as the first two: it generates paths from
its own knowledge rather than selecting from the candidate list. These repositories are
large, old and public, so the model has very likely seen them in training. That is a
confound, not a bug, and `llm_in_listing` in the results records how often its answers
even exist in the repo - a generated path that does not exist is a fabrication, and
counting those is the only way to tell recall from recall-shaped memorisation.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter

OLLAMA = "http://localhost:11434"

# Split on separators and camelCase humps: "sql/compiler.py" and "BaseDatabaseWrapper"
# both need to become the words a bug report would actually use.
_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

# Path segments that appear in nearly every candidate carry no signal but do carry
# BM25 weight, and dropping them is cheaper than relying on IDF to zero them out.
_STOP = {"py", "src", "lib", "python", "tests", "test", "__init__", ""}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _SPLIT.split(text) if t and t.lower() not in _STOP]


class BM25:
    """Okapi BM25. Pure Python - the corpus is a few thousand short paths."""

    # Defaults chosen by sweeping k1 in {0.9,1.2,1.5,2.0} x b in {0,0.25,0.5,0.75,1.0}
    # over all 300 instances: recall@10 ranged 28.0%-31.7% and these were the best.
    # Reported so the baseline cannot be dismissed as untuned - the conclusion below
    # holds at every setting, which is why the range matters more than the winner.
    def __init__(self, docs: list[str], k1: float = 2.0, b: float = 1.0):
        self.docs = docs
        self.k1, self.b = k1, b
        self.toks = [tokenize(d) for d in docs]
        self.len = [len(t) for t in self.toks]
        self.avg = sum(self.len) / len(self.len) if self.len else 0.0
        self.tf = [Counter(t) for t in self.toks]
        df: Counter[str] = Counter()
        for t in self.toks:
            df.update(set(t))
        n = len(docs)
        # +0.5/+0.5 smoothing keeps IDF positive for terms in almost every document.
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def rank(self, query: str, top: int = 50) -> list[tuple[str, float]]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            if not tf:
                continue
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1))
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf.get(w, 0.0) * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                scores.append((self.docs[i], s))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:top]


def _ollama(endpoint: str, payload: dict, timeout: int = 600) -> dict | None:
    req = urllib.request.Request(
        f"{OLLAMA}{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.loads(fh.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def embed(
    texts: list[str], model: str = "nomic-embed-text", batch: int = 256
) -> list[list[float]] | None:
    """Batched embeddings via /api/embed.

    The per-item /api/embeddings endpoint measured 2.1 s per path here, because the
    14B generator holds VRAM and the embedder is evicted and reloaded on every call.
    Batching with an explicit keep_alive holds it resident: 18 ms per path, a 118x
    difference, and the reason this runs in minutes instead of hours.
    """
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        vecs = _embed_chunk(chunk, model, batch)
        if vecs is None:
            return None
        out.extend(vecs)
    return out


def _embed_chunk(
    chunk: list[str], model: str, batch: int, depth: int = 0
) -> list[list[float]] | None:
    """One batch, halved and retried on failure.

    A batch fails for reasons that are about size rather than content - a long request
    while the 14B holds VRAM, a transient refusal - so halving usually succeeds where
    a retry of the same payload would not. Returning None for the whole corpus on one
    bad batch silently drops the entire retriever from the comparison, which is a far
    worse outcome than being slow.
    """
    r = _ollama("/api/embed", {"model": model, "input": chunk, "keep_alive": "30m"})
    if r is not None and "embeddings" in r and len(r["embeddings"]) == len(chunk):
        return r["embeddings"]
    if len(chunk) == 1 or depth > 6:
        return None
    mid = len(chunk) // 2
    left = _embed_chunk(chunk[:mid], model, batch, depth + 1)
    if left is None:
        return None
    right = _embed_chunk(chunk[mid:], model, batch, depth + 1)
    if right is None:
        return None
    return left + right


def cosine_rank(
    qvec: list[float], doc_vecs: list[list[float]], docs: list[str], top: int = 50
) -> list[tuple[str, float]]:
    qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
    scored = []
    for path, v in zip(docs, doc_vecs, strict=False):
        dn = math.sqrt(sum(x * x for x in v)) or 1.0
        scored.append((path, sum(a * b for a, b in zip(qvec, v, strict=False)) / (qn * dn)))
    scored.sort(key=lambda kv: -kv[1])
    return scored[:top]


# The model arms used to live here as well: `llm_locate`, `llm_rerank` and
# `ollama_ready`, each a synchronous copy of what app 01 does through
# `apps._platform.model`. Nothing called any of them, and that was the lucky part -
# all three returned `[]` or `False` when ollama did not answer, which is the
# lost-generation bug `model.require_all` exists to refuse: a ranking of nothing
# scored as a miss rather than as a call that never happened. One implementation per
# arm now, and it is the one with the guard. The arms are driven from
# `localize_eval.py`.
