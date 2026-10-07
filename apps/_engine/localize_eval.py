"""The localization measurement, as a command rather than as loose parts.

The root README says what this repository can show you offline is "the measurement
code". Every piece of it was here and nothing composed them: `evaluate.print_report`,
`trees.commit_listings`, `trees.listing_for` and `differential.find_many` had no
callers anywhere in the repository. (This sentence listed `trees.fetch_at_commit`
among them and this module does not call it: fetching is not on the evaluation path,
deliberately, and `scripts/fetch_trees.py` is what calls it.) The pieces were the
fingerprint of a driver that had been run on this machine and never committed, so the
headline - BM25 collapsing from 38/51 to 13/154 depending only on whether the issue
quotes the file path - could not be reproduced from the repository that states it.

The second figure was 13/153 for a while, because this driver dropped the one instance
whose gold file is absent from its repo listing. `apps/_engine/evaluate.py` states the
opposite rule and gives the reason, and this was the only caller breaking it. The tier
table prints the fraction beside every rate as well, because 51 and 18 instances do not
support the decimal place the old table printed.

This is that driver. The lexical arm needs nothing but the files already on disk: the
SWE-bench Lite parquet in the Hugging Face cache and the tree listings under
`data/trees`. The dense and generative arms need a model and are opt-in, because a
measurement you cannot run is the thing this module exists to stop.

    python -m apps._engine.localize_eval                  # BM25, offline
    python -m apps._engine.localize_eval --embed          # adds the dense arm
    python -m apps._engine.localize_eval --model-arms     # adds the two model arms
    python -m apps._engine.localize_eval --json out.json

Candidate sets come from `listing_for`, so the per-commit repair is applied rather than
merely available: scikit-learn renamed most of its modules behind underscores, and a
repo-level listing taken at one commit is missing a third of its gold files at others.
That repair existed in `trees.py` with nothing calling it, which means every score this
app has ever printed carried the automatic-miss floor its docstring says it removes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps._engine.evaluate import (  # noqa: E402
    KS,
    fabrication_rate,
    print_report,
    resolve,
    summarize,
)
from apps._engine.locate_prompts import (  # noqa: E402
    LOCATE_PROMPT,
    RERANK_PROMPT,
    dropped_lines,
    parse_choices,
    parse_paths,
)
from apps._engine.mention_analysis import tier_for  # noqa: E402
from apps._engine.retrieval import BM25, cosine_rank  # noqa: E402
from apps._engine.swebench_data import Instance, load  # noqa: E402
from apps._engine.trees import (  # noqa: E402
    cached_repos,
    commit_listings,
    coverage,
    listing_for,
    source_files,
)


def candidates(inst: Instance, repos: dict, at_commit: dict) -> list[str]:
    """The files a retriever may rank for this instance."""
    return source_files(listing_for(inst, repos, at_commit))


def _rows(
    inst: Instance,
    files: list[str],
    ranked: list[str],
    retriever: str,
    *,
    unparsed: int = 0,
) -> dict:
    """One scored instance.

    ``unparsed`` is how many lines of the model's reply named nothing this harness
    could read. It is carried per row rather than totalled at the end because it has
    to stay separate from the fabrication count: a line the parser could not read is
    a fact about the parser, and reporting it as an invented path would be a claim
    about the model. Retrievers that do not read a reply leave it at zero.
    """
    return {
        "instance_id": inst.instance_id,
        "repo": inst.repo,
        "tier": tier_for(inst, inst.problem_statement),
        "gold": inst.gold_files[0],
        "ranked": ranked,
        "retriever": retriever,
        "unparsed": unparsed,
    }


def run(
    limit: int | None = None,
    *,
    embed: bool = False,
    model_arms: bool = False,
    quiet: bool = False,
) -> dict:
    """Score every instance whose candidate set is on disk, and say which were not.

    The skipped instances are returned rather than dropped. A recall figure over the
    instances that happened to have a cached listing, reported as a recall figure over
    SWE-bench Lite, is the shape of mistake the rest of this repository is about.
    """
    instances = load(limit)
    repos = cached_repos()
    at_commit = commit_listings()

    results: list[dict] = []
    scored: list[Instance] = []
    no_listing: list[str] = []
    gold_absent: list[str] = []

    for inst in instances:
        files = candidates(inst, repos, at_commit)
        if not files:
            no_listing.append(inst.instance_id)
            continue
        # A gold file outside the candidate set is an automatic miss, and it is SCORED
        # as one rather than dropped. `apps/_engine/evaluate.py` states the rule this
        # file is graded by - "an instance whose gold file is missing from the repo
        # listing is kept in the denominator and scored as a miss. It cannot be
        # retrieved by anything, so dropping it would flatter every retriever equally
        # and by an amount nobody could see" - and this was the one caller doing the
        # opposite.
        #
        # One instance is affected, django__django-15388, and it is in the
        # `not_mentioned` tier: the hard half the headline is about. Dropping it made
        # the figure 13/153 = 8.4967%, printed as 8.5%; keeping it makes it 13/154 =
        # 8.4416%, printed as 8.4%. The README had dismissed an earlier "8.4%" as
        # "13/153 rounded the wrong way", which resolved a rounding complaint by
        # adopting the flattering denominator.
        #
        # It matters more for the generative arm than for this one: a model naming
        # files freely is not limited to the listing, so for it the instance is
        # retrievable and excluding it would hide a real failure.
        if inst.gold_files[0] not in set(files):
            gold_absent.append(inst.instance_id)
        scored.append(inst)
        bm = BM25(files)
        results.append(
            _rows(inst, files, [p for p, _ in bm.rank(inst.problem_statement, 20)], "bm25")
        )

    if embed:
        results.extend(_embed_arm(scored, repos, at_commit, quiet=quiet))
    if model_arms:
        results.extend(_model_arms(scored, repos, at_commit, quiet=quiet))

    recall = summarize(results, KS)
    # `fabrication_rate` is the producer of the fabrication figure, and it had no
    # caller anywhere in the repository, so the claim the README used to make had no
    # producer - the generative arm is the only thing that can produce it, and the arm
    # had no driver either until this module existed. The README's "one path in five"
    # has since been withdrawn as well: it was measured by a parser that charged the
    # model for shapes it could not read. `fabrication_rate`
    # computes exactly that and had no caller anywhere in the repository, so the
    # claim had no producer - the generative arm is the only thing that can produce
    # it, and the arm had no driver either until this module existed.
    listings = {inst.repo: candidates(inst, repos, at_commit) for inst in scored}
    fabrication = {
        name: fabrication_rate([r for r in results if r["retriever"] == name], listings)
        for name in ("llm", "llm_rerank")
        if any(r["retriever"] == name for r in results)
    }
    population = {
        "instances_loaded": len(instances),
        "scored": len(scored),
        "no_cached_listing": len(no_listing),
        "gold_file_not_in_listing": len(gold_absent),
        # The approximation's cost, over the instances that were scored. Computed
        # here rather than inferred from the two counts above: an instance can be
        # missing a listing and have a gold file that would not have been in it.
        "listing_coverage": coverage(instances, repos),
        "per_commit_listings_used": sum(
            1 for i in scored if (i.repo, i.base_commit[:12]) in at_commit
        ),
    }
    # The recall figures and the population they are over, kept apart:
    # iterates its argument as retrievers, and a population dict folded in beside them
    # is read as one.
    return {
        "recall": recall,
        "fabrication": fabrication,
        "population": population,
        "skipped": {"no_cached_listing": no_listing, "gold_not_in_listing": gold_absent},
    }


def _embed_arm(scored: list[Instance], repos: dict, at_commit: dict, *, quiet: bool) -> list[dict]:
    """The dense arm. Opt-in, because it needs a model running."""
    import asyncio

    from apps._platform import model

    async def go() -> list[dict]:
        out: list[dict] = []
        for i, inst in enumerate(scored, 1):
            files = candidates(inst, repos, at_commit)
            doc_vecs = await model.embed(files)
            if not doc_vecs:
                raise RuntimeError(
                    "the embedding model returned nothing; no rate is published from a "
                    "partial run. Start ollama or drop --embed."
                )
            query = await model.embed([inst.problem_statement])
            ranked = [p for p, _ in cosine_rank(query[0], doc_vecs, files, 20)]
            out.append(_rows(inst, files, ranked, "embed"))
            if not quiet and i % 25 == 0:
                print(f"  embedded {i}/{len(scored)}", file=sys.stderr)
        return out

    return asyncio.run(go())


def _model_arms(scored: list[Instance], repos: dict, at_commit: dict, *, quiet: bool) -> list[dict]:
    """The generative and reranking arms, which is the comparison the finding needs.

    Both go through `apps._platform.model`, so a generation that never reached the
    model raises rather than being scored as a ranking that found nothing. There used
    to be a second, synchronous implementation of each in `retrieval.py` which
    returned an empty list on an unreachable ollama; nothing called either, and this
    is the one that replaces them.

    Not run here. The coder model is 14B and this machine's GPU is reserved, so these
    arms are opt-in and the repository does not claim a number from them.
    """
    import asyncio

    from apps._platform import model

    async def go() -> list[dict]:
        out: list[dict] = []
        for i, inst in enumerate(scored, 1):
            files = candidates(inst, repos, at_commit)
            listing = set(files)

            raw = await model.generate(
                LOCATE_PROMPT.format(repo=inst.repo, issue=inst.problem_statement[:6000]),
                num_predict=256,
            )
            reply = model.require(raw, what="ranking")
            named = parse_paths(reply)
            out.append(
                _rows(
                    inst,
                    files,
                    resolve(named, listing),
                    "llm",
                    unparsed=len(dropped_lines(reply)),
                )
            )

            # Selecting from a supplied list makes fabrication impossible, so the gap
            # between this arm and the one above is the size of the memorisation effect.
            pool = [p for p, _ in BM25(files).rank(inst.problem_statement, 30)]
            numbered = chr(10).join(f"{n + 1}. {p}" for n, p in enumerate(pool))
            raw2 = await model.generate(
                RERANK_PROMPT.format(
                    repo=inst.repo, issue=inst.problem_statement[:5000], candidates=numbered
                ),
                num_predict=128,
            )
            out.append(
                _rows(
                    inst,
                    files,
                    parse_choices(model.require(raw2, what="rerank"), pool, 10),
                    "llm_rerank",
                )
            )
            if not quiet and i % 10 == 0:
                print(f"  model arms {i}/{len(scored)}", file=sys.stderr)
        return out

    return asyncio.run(go())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="localize_eval",
        description="Recall@k for file localization on SWE-bench Lite, by mention tier.",
    )
    parser.add_argument("--limit", type=int, default=None, help="score at most N instances")
    parser.add_argument("--embed", action="store_true", help="add the dense arm (needs a model)")
    parser.add_argument(
        "--model-arms",
        action="store_true",
        help="add the generative and reranking arms (needs the coder model)",
    )
    parser.add_argument("--json", help="write the summary here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run(args.limit, embed=args.embed, model_arms=args.model_arms, quiet=args.quiet)
    except RuntimeError as exc:
        # One line and exit 2, like every CLI in `projects/`. The lexical arm needs
        # nothing but the committed data; `--embed` and `--model-arms` need a model, and
        # a model that is not up is the caller's situation rather than a bug - it came
        # back as a full traceback from the repository's flagship reproducible command.
        print(f"{exc}", file=sys.stderr)
        return 2
    print_report(summary["recall"], KS)

    population = summary["population"]
    print("\n  POPULATION")
    print(f"    instances loaded              {population['instances_loaded']}")
    print(f"    scored                        {population['scored']}")
    print(f"    no cached listing             {population['no_cached_listing']}")
    print(f"    gold file not in the listing  {population['gold_file_not_in_listing']}")
    print(f"    scored from a per-commit listing  {population['per_commit_listings_used']}")
    # What the one-tree-per-repository approximation costs, which is the ceiling every
    # rate above is measured against. `trees.py`'s overview argues from this figure and
    # nothing computed it: the two symptoms were printed - instances with no listing,
    # instances whose gold file is absent from one - without the number they come to.
    reach = population["listing_coverage"]
    if reach["rate"] is None:
        print(f"    listing coverage              not measured ({reach['unlistable']} unlistable)")
    else:
        print(
            f"    listing coverage              {reach['covered']}/{reach['total']} "
            f"({reach['rate']:.1%}) - the ceiling every rate above is measured against"
        )
    if population["scored"] != population["instances_loaded"]:
        print("    Every rate above is over `scored`, never over `instances loaded`.")

    if summary["fabrication"]:
        print("\n  FABRICATION  (named paths that exist in the repository)")
        for name, found in summary["fabrication"].items():
            print(
                f"    {name:12} {found['paths_that_exist']:5}/{found['paths_named']:<5} "
                f"{found['rate_exists']:6.1%} real   over {found['instances_scored']} "
                f"instance(s), {found['instances_unlistable']} unlistable, "
                f"{found['lines_unparsed']} line(s) unparsed"
            )
        print(
            "    An unparsed line named nothing this harness could read. It is not a "
            "fabrication: the model answered and the parser did not understand it, "
            "so the two are counted apart."
        )
    elif not args.model_arms:
        print("\n  FABRICATION  not measured: it needs --model-arms")

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
