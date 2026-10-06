"""The localization measurement driver, and the dead parts it replaced.

The root README says what this repository can show you offline is "the measurement
code". Every piece was here and nothing composed them: `evaluate.print_report`,
`trees.commit_listings`, `trees.listing_for`, `trees.fetch_at_commit` and
`differential.find_many` had no caller anywhere in the repository, which is the
fingerprint of a driver that was run on this machine and never committed. The headline
— BM25 at 38 of 51 when the issue quotes the file path and 13 of 153 when it does not — could
not be reproduced from the repository stating it.

`localize_eval` is that driver, and these are the properties worth holding:

- the candidate set comes from `listing_for`, so the per-commit repair is applied
  rather than merely available. Without it 22 instances have a gold file missing from
  the listing and are dropped, which raises recall@10 from 34.1% to 34.3% off a
  denominator 7% smaller;
- instances it cannot score are returned, not dropped silently;
- there is one implementation of each model arm, and it is the one that refuses to
  publish a rate from a generation that never happened.

The runs over real SWE-bench data skip when the parquet is not in the local Hugging
Face cache, naming it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps._engine import localize_eval as le  # noqa: E402
from apps._engine.swebench_data import Instance, find_parquet  # noqa: E402

HAVE_DATA = find_parquet() is not None and (ROOT / "data" / "trees").is_dir()
needs_data = pytest.mark.skipif(
    not HAVE_DATA, reason="SWE-bench Lite parquet or data/trees is not on this machine"
)


# -- the candidate set ----------------------------------------------------


def _instance(repo: str = "scikit-learn/scikit-learn", commit: str = "a" * 40) -> Instance:
    return Instance(
        instance_id=f"{repo.split('/')[-1]}-1",
        repo=repo,
        base_commit=commit,
        problem_statement="OneHotEncoder raises on unknown categories",
        hints_text="",
        gold_files=("sklearn/preprocessing/_encoders.py",),
    )


def test_an_exact_commit_listing_is_preferred_over_the_repo_level_one():
    """`listing_for` existed with no caller, so the repair never ran.

    scikit-learn moved most of its modules behind underscore names, so a repo-level
    listing taken at one commit is missing a third of its gold files at others.
    """
    inst = _instance(commit="b" * 40)
    repos = {inst.repo: ["sklearn/preprocessing/encoders.py", "setup.py"]}
    at_commit = {(inst.repo, "b" * 12): ["sklearn/preprocessing/_encoders.py", "setup.py"]}

    exact = le.candidates(inst, repos, at_commit)
    assert inst.gold_files[0] in exact

    approximate = le.candidates(inst, repos, {})
    assert inst.gold_files[0] not in approximate, "which is an automatic miss"


def test_the_repo_level_listing_is_used_when_there_is_no_exact_one():
    inst = _instance()
    repos = {inst.repo: ["sklearn/preprocessing/_encoders.py"]}
    assert le.candidates(inst, repos, {}) == ["sklearn/preprocessing/_encoders.py"]


def test_an_instance_with_no_listing_at_all_yields_no_candidates():
    assert le.candidates(_instance(), {}, {}) == []


# -- the population -------------------------------------------------------


@needs_data
def test_the_population_is_reported_rather_than_assumed():
    """A recall figure over the instances that happened to have a listing, reported
    as a recall figure over SWE-bench Lite, is the shape of mistake this repository
    is about."""
    out = le.run(limit=40)
    population = out["population"]

    assert population["instances_loaded"] == 40
    assert population["scored"] <= population["instances_loaded"]
    assert (
        population["scored"]
        + population["no_cached_listing"]
        + population["gold_file_not_in_listing"]
        == population["instances_loaded"]
    ), "every instance lands in exactly one bucket"
    assert len(out["skipped"]["no_cached_listing"]) == population["no_cached_listing"]
    assert len(out["skipped"]["gold_not_in_listing"]) == population["gold_file_not_in_listing"]


@needs_data
def test_the_recall_figures_are_kept_apart_from_the_population():
    """`print_report` iterates its argument as retrievers; a population dict folded
    in beside them was read as one and crashed on a missing 'overall' key."""
    out = le.run(limit=10)
    assert set(out) == {"recall", "fabrication", "population", "skipped"}
    for name, scores in out["recall"].items():
        assert {"overall", "by_tier", "by_repo"} <= set(scores), name
        assert "recall@10" in scores["overall"]


@needs_data
def test_the_per_commit_repair_adds_instances_rather_than_improving_the_score():
    """What it is worth, measured both ways.

    Dropping the 22 instances whose gold file is absent from a repo-level listing is
    the denominator doing the work: the rate goes up slightly because the instances
    removed are harder than average.
    """
    import apps._engine.localize_eval as module

    real = module.commit_listings
    with_repair = le.run(limit=300)
    try:
        module.commit_listings = dict
        without = le.run(limit=300)
    finally:
        module.commit_listings = real

    assert with_repair["population"]["scored"] > without["population"]["scored"]
    assert (
        without["population"]["gold_file_not_in_listing"]
        > with_repair["population"]["gold_file_not_in_listing"]
    )
    assert with_repair["population"]["per_commit_listings_used"] > 0


@needs_data
def test_bm25_reproduces_the_headline_the_root_readme_states():
    """38 of 51 when the issue quotes the path, 13 of 153 when it does not.

    Pinned as fractions, not as rates. The README quoted `74.5%` on 51 instances, where
    one instance is two percentage points, so the decimal place was a digit the sample
    could not support - and the same headline appeared elsewhere as `8.4%`, which is
    13/153 rounded the wrong way. A fraction cannot be rounded wrongly, and it is the
    form the tier table now prints.
    """
    out = le.run()
    tiers = out["recall"]["bm25"]["by_tier"]

    assert out["population"]["scored"] == 299
    assert (tiers["full_path"]["hits@10"], tiers["full_path"]["n"]) == (38, 51)
    assert (tiers["not_mentioned"]["hits@10"], tiers["not_mentioned"]["n"]) == (13, 153)
    assert (tiers["basename"]["hits@10"], tiers["basename"]["n"]) == (12, 18)
    assert (tiers["stem_only"]["hits@10"], tiers["stem_only"]["n"]) == (39, 77)
    # The four tiers are the whole scored population, so none of them is a subset
    # quietly standing in for the rest.
    assert sum(t["n"] for t in tiers.values()) == 299
    assert tiers["full_path"]["recall@10"] > tiers["not_mentioned"]["recall@10"] * 8

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "75% (38 of 51)" in readme
    assert "8.5% (13 of 153)" in readme, "it said 8.4%, which is 13/153 rounded the wrong way"
    assert "74.5%" not in readme, "the over-precise form is back"


# -- one implementation per arm -------------------------------------------


def test_the_duplicate_synchronous_model_arms_are_gone():
    """They returned [] when ollama did not answer, which `require_all` refuses.

    Nothing called `retrieval.llm_locate`, `retrieval.llm_rerank` or
    `retrieval.ollama_ready`, and that was the lucky part: a ranking of nothing would
    have been scored as a miss rather than as a call that never happened.
    """
    from apps._engine import retrieval

    for gone in ("llm_locate", "llm_rerank", "ollama_ready"):
        assert not hasattr(retrieval, gone), f"{gone} is back"


def test_there_is_one_home_for_the_prompts_and_parsers():
    from apps._engine import locate_prompts

    assert hasattr(locate_prompts, "LOCATE_PROMPT")
    assert hasattr(locate_prompts, "RERANK_PROMPT")

    app = (ROOT / "apps" / "01_localizer" / "app.py").read_text(encoding="utf-8")
    assert "from apps._engine.locate_prompts import" in app
    assert 'LOCATE_PROMPT = """' not in app, "app 01 held a second copy of the prompt"
    assert "def _parse_paths(" not in app, "and a second copy of the parser"


def test_the_shared_parser_reads_what_a_model_actually_returns():
    from apps._engine.locate_prompts import parse_choices, parse_paths

    named = parse_paths("1. `django/db/models/query.py`\n2. ./foo/bar.py\nsome prose\nbaz.py\n")
    assert named == ["django/db/models/query.py", "foo/bar.py", "baz.py"]

    # A reply in prose yields nothing. Falling back to the input order would report
    # the lexical ranking's score under the reranker's name.
    assert parse_choices("I think the bug is in the parser.", ["a.py", "b.py"]) == []
    assert parse_choices("2\n1\n", ["a.py", "b.py"]) == ["b.py", "a.py"]


def test_the_unused_parallel_witness_wrapper_is_gone():
    from apps._engine import differential

    assert not hasattr(differential, "find_many")
    assert hasattr(differential, "find_witness")


# -- the fabrication rate, which had no caller ----------------------------


class _NamingModel:
    """A model that names two real paths and one it invented, per instance."""

    def __init__(self):
        self.calls = 0

    async def generate(self, prompt: str, num_predict: int = 256) -> str:
        self.calls += 1
        if "numbered list of candidate files" in prompt or "CANDIDATES:" in prompt:
            return "1\n2\n"
        return "sklearn/preprocessing/_encoders.py\nsetup.py\nsklearn/invented/nowhere.py\n"

    def require(self, raw, what: str = ""):
        assert raw is not None, what
        return raw


@needs_data
def test_the_fabrication_rate_is_computed_by_the_driver(monkeypatch):
    """The README says the model "invents one path in five".

    `evaluate.fabrication_rate` computes exactly that and had no caller anywhere -
    the commit that composed the other four orphaned pieces left this one out, and
    `print_report` never printed it. So the claim had no producer in the repository
    that makes it.
    """
    from apps._platform import model as platform_model

    stub = _NamingModel()
    monkeypatch.setattr(platform_model, "generate", stub.generate)
    monkeypatch.setattr(platform_model, "require", stub.require)

    out = le.run(limit=3, model_arms=True, quiet=True)

    assert "llm" in out["fabrication"], "the generative arm did not reach the rate"
    found = out["fabrication"]["llm"]
    assert found["paths_named"] > 0
    assert found["paths_that_exist"] <= found["paths_named"]
    assert 0.0 <= found["rate_exists"] <= 1.0
    # The invented path must not count as real, which is the whole point.
    assert found["paths_that_exist"] < found["paths_named"]
    assert found["instances_scored"] + found["instances_unlistable"] >= 1
    assert stub.calls >= 2, "both model arms should have been driven"


@needs_data
def test_the_report_says_when_fabrication_was_not_measured():
    """Rather than leaving a README claim with nothing beside it."""
    out = le.run(limit=3)
    assert out["fabrication"] == {}, "no model arm ran, so there is nothing to report"
