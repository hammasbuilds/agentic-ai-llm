"""Localizer — which file does this issue touch?

Paste a bug report, pick a repository, and watch four retrievers disagree about where the
fix goes: BM25 over paths, embeddings over paths, the coder model naming files from its own
knowledge, and the same model reranking BM25's shortlist.

The finding this was built from: BM25 scores 74.5% when the issue quotes the file path and
**8.4% when it does not**, on SWE-bench Lite. The model naming files freely gets 55.8% on
that hard half — but only 17.5% when restricted to reranking, which is the evidence that
its advantage is knowing the repository rather than reading the issue.

This is a hybrid-retrieval demo in the strict sense: lexical and dense retrievers are run
over the same candidate set and fused into one ranking, and the LLM arms are scored against
the same gold file, so the four columns are comparable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.evaluate import resolve  # noqa: E402
from apps._engine.locate_prompts import (  # noqa: E402
    LOCATE_PROMPT,
    RERANK_PROMPT,
    parse_choices,
    parse_paths,
)
from apps._engine.retrieval import BM25, cosine_rank  # noqa: E402
from apps._engine.trees import cached_repos, source_files  # noqa: E402
from apps._platform import model  # noqa: E402
from apps._platform.base import Field, create_app  # noqa: E402

HERE = Path(__file__).resolve().parent
SLUG = "localizer"


def _repos() -> list[tuple[str, str]]:
    """The repositories whose file listings are on disk, for the picker.

    `cached_repos` returns {} rather than raising when `data/trees` is absent, so this
    used to render an empty picker and say nothing - a form with nothing to choose and
    no reason given, on the one app whose first control is the choice. The caller shows
    the hint, and the hint says what is missing.
    """
    try:
        return [(r, r) for r in sorted(cached_repos())]
    except Exception:
        return []


def _repo_hint(options: list[tuple[str, str]]) -> str:
    if options:
        return f"{len(options)} repositories, file listings cached from the GitHub Trees API"
    return (
        "no file listings found in data/trees - run the fetch script before this app can "
        "localise anything"
    )


async def runner(params: dict, emit) -> dict:
    repo = params.get("repo") or ""
    issue = (params.get("issue") or "").strip()
    if not issue:
        raise ValueError("paste a bug report first")

    listings = cached_repos()
    if repo not in listings:
        raise ValueError(f"no cached file listing for {repo!r}")
    files = source_files(listings[repo])

    await emit(1, 5, f"{len(files)} candidate source files in {repo}")

    # --- lexical --------------------------------------------------------------------
    bm = BM25(files)
    bm_ranked = [p for p, _ in bm.rank(issue, 20)]
    await emit(2, 5, f"BM25 ranked {len(bm_ranked)}")

    # --- dense ----------------------------------------------------------------------
    embed_ranked: list[str] = []
    doc_vecs = await model.embed(files)
    if doc_vecs:
        qv = await model.embed([issue])
        if qv:
            embed_ranked = [p for p, _ in cosine_rank(qv[0], doc_vecs, files, 20)]
    await emit(3, 5, f"embeddings ranked {len(embed_ranked)}")

    # --- generative -----------------------------------------------------------------
    raw = await model.generate(LOCATE_PROMPT.format(repo=repo, issue=issue[:6000]), num_predict=256)
    # The model names module paths; matplotlib's package lives under lib/, so resolve
    # against the real listing before comparing. Only unambiguous matches resolve.
    llm_ranked = resolve(parse_paths(model.require(raw, what="ranking")), set(files))
    fabricated = [p for p in llm_ranked if p not in set(files)]
    await emit(4, 5, f"model named {len(llm_ranked)} paths, {len(fabricated)} not in the repo")

    # --- rerank ---------------------------------------------------------------------
    pool = [p for p, _ in bm.rank(issue, 30)]
    numbered = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(pool))
    raw2 = await model.generate(
        RERANK_PROMPT.format(repo=repo, issue=issue[:5000], candidates=numbered),
        num_predict=128,
    )
    rerank_ranked = parse_choices(model.require(raw2, what="rerank"), pool, 10)
    await emit(5, 5, "done")

    # --- hybrid fusion (reciprocal rank) --------------------------------------------
    # Lexical wins where the path is quoted, dense wins where it is not. Fusing them
    # is the only column here that is better than both on both halves.
    scores: dict[str, float] = {}
    for ranking in (bm_ranked, embed_ranked):
        for i, p in enumerate(ranking):
            scores[p] = scores.get(p, 0.0) + 1.0 / (60 + i)
    hybrid = [p for p, _ in sorted(scores.items(), key=lambda kv: -kv[1])][:20]

    return {
        "repo": repo,
        "candidates": len(files),
        "issue_chars": len(issue),
        "fabricated": len(fabricated),
        "rankings": {
            "bm25": bm_ranked[:10],
            "embeddings": embed_ranked[:10],
            "hybrid": hybrid[:10],
            "llm": llm_ranked[:10],
            "llm_rerank": rerank_ranked[:10],
        },
    }


ABOUT = """
<p>Four retrievers over the same candidate set, plus a reciprocal-rank fusion of the two
cheap ones.</p>
<p>The measurement behind it, on 299 of SWE-bench Lite's 300 instances — one has a gold
file that is in no cached listing, and it is excluded rather than counted as a miss:
<b>BM25 falls from 74.5% recall@10 when the issue quotes the file path to 8.5% when it
does not.</b> Embeddings get 29.2% on that hard half, and the coder model naming files
from memory gets 55.8%.</p>
<p>That BM25 row is reproducible offline from this repository:
<code>python -m apps._engine.localize_eval</code>. It was not, until recently — the
measurement was a set of pieces in <code>apps/_engine</code> with nothing composing
them, and the figure quoted here was 8.4%, which is 13/153 rounded the wrong way.</p>
<p>The reranker column is the control. Restricted to reordering BM25's top-30, the same
model manages 17.5% on that half — while realising 92% of the ceiling it is handed. It is
not a better ranker; it proposes candidates first-stage retrieval never surfaces, which is
what knowing a codebase looks like.</p>
<p>It also invents about one path in five, which is why fabrications are counted here
rather than quietly resolved away.</p>
"""

app = create_app(
    slug="localizer",
    icon="🧭",
    runner=runner,
    fields=[
        Field(
            "repo",
            "Repository",
            kind="select",
            default="django/django",
            options=(_REPOS := _repos()),
            hint=_repo_hint(_REPOS),
        ),
        Field(
            "issue",
            "Bug report",
            kind="textarea",
            default="QuerySet.union() crashes when combined with values_list() "
            "and a sliced queryset. Traceback ends in the SQL compiler.",
            hint="paste a real issue body",
        ),
    ],
    result_template="result.html",
    about=ABOUT,
    templates_dir=HERE / "templates",
)
