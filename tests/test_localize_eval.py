"""The localization measurement driver, and the dead parts it replaced.

The root README says what this repository can show you offline is "the measurement
code". Every piece was here and nothing composed them: `evaluate.print_report`,
`trees.commit_listings`, `trees.listing_for`, `trees.fetch_at_commit` and
`differential.find_many` had no caller anywhere in the repository, which is the
fingerprint of a driver that was run on this machine and never committed. The headline
— BM25 at 38 of 51 when the issue quotes the file path and 13 of 154 when it does not — could
not be reproduced from the repository stating it.

`localize_eval` is that driver, and these are the properties worth holding:

- the candidate set comes from `listing_for`, so the per-commit repair is applied
  rather than merely available. Without it 23 instances have a gold file missing from
  the listing instead of 1, and recall@10 is 31.67% rather than 34.00% over the same
  300 - a real gain on a fixed denominator. It used to read "34.1% to 34.3% off a
  denominator 7% smaller", because those instances were dropped rather than scored, so
  the repair's value showed up as a denominator shrinking instead of as gold files
  becoming findable;
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
def test_the_per_commit_repair_makes_gold_files_findable_on_a_fixed_denominator():
    """What it is worth, measured both ways over the same population.

    This used to assert that the repair ADDED instances - `scored` went up - which was
    true only because an instance whose gold file is absent from the listing was
    dropped. `apps/_engine/evaluate.py` says such an instance stays in the denominator
    and is scored as a miss, so the population is 300 either way now and the repair's
    value is where it belongs: 22 more gold files in the candidate set, and recall@10
    rising 31.67% -> 34.00% rather than a rate climbing because the hard instances left.
    """
    import apps._engine.localize_eval as module

    real = module.commit_listings
    with_repair = le.run(limit=300)
    try:
        module.commit_listings = dict
        without = le.run(limit=300)
    finally:
        module.commit_listings = real

    # Same denominator both ways. That is the point of the change.
    assert with_repair["population"]["scored"] == without["population"]["scored"] == 300
    assert with_repair["population"]["gold_file_not_in_listing"] == 1
    assert without["population"]["gold_file_not_in_listing"] == 23
    assert with_repair["population"]["per_commit_listings_used"] > 0

    gained = with_repair["recall"]["bm25"]["overall"]["recall@10"]
    base = without["recall"]["bm25"]["overall"]["recall@10"]
    assert round(base * 100, 2) == 31.67, base
    assert round(gained * 100, 2) == 34.00, gained


@needs_data
def test_bm25_reproduces_the_headline_the_root_readme_states():
    """38 of 51 when the issue quotes the path, 13 of 154 when it does not.

    This docstring said 153, which is the figure the test below it exists to reject -
    the denominator that drops the instance whose gold file is absent from its own
    repository listing. Nothing retrieves a file that is not there, so excluding it
    flatters every retriever equally and by an amount nobody can see.

    Pinned as fractions, not as rates. The README quoted `74.5%` on 51 instances, where
    one instance is two percentage points, so the decimal place was a digit the sample
    could not support - and the same headline appeared elsewhere as `8.4%`, which was
    then defended as "13/153 rounded the wrong way", resolving a rounding complaint by
    adopting the flattering denominator. A fraction cannot be rounded wrongly, and it
    is the form the tier table now prints.
    """
    out = le.run()
    tiers = out["recall"]["bm25"]["by_tier"]

    assert out["population"]["scored"] == 300
    assert (tiers["full_path"]["hits@10"], tiers["full_path"]["n"]) == (38, 51)
    assert (tiers["not_mentioned"]["hits@10"], tiers["not_mentioned"]["n"]) == (13, 154)
    assert (tiers["basename"]["hits@10"], tiers["basename"]["n"]) == (12, 18)
    assert (tiers["stem_only"]["hits@10"], tiers["stem_only"]["n"]) == (39, 77)
    # The four tiers are the whole scored population, so none of them is a subset
    # quietly standing in for the rest.
    assert sum(t["n"] for t in tiers.values()) == 300
    # The gap, as the two fractions rather than as a multiple of one rate by the other.
    # `> ... * 8` was a floor where the exact pair is already asserted four lines up,
    # and it would pass on any number of pathological pairs that satisfy it.
    assert tiers["full_path"]["recall@10"] == pytest.approx(38 / 51)
    assert tiers["not_mentioned"]["recall@10"] == pytest.approx(13 / 154)
    assert tiers["full_path"]["recall@10"] / tiers["not_mentioned"]["recall@10"] == (
        pytest.approx(8.82, abs=0.01)
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "75% (38 of 51)" in readme
    assert "8.4% (13 of 154)" in readme, (
        "8.4% is 13/154, the denominator `evaluate.py` mandates. 8.5% is 13/153, which "
        "drops the instance whose gold file is absent from its listing."
    )
    assert "74.5%" not in readme, "the over-precise form is back"
    assert "13 of 153" not in readme, "the flattering denominator is back"

    # The paragraph that states the rule, which is a separate thing from the figure.
    # It described the OPPOSITE rule - "excluded rather than counted as a retrieval
    # failure" - forty lines above a headline computed the other way, and nothing here
    # read it. A figure can be right while the sentence explaining it is wrong, and a
    # reader takes the sentence.
    assert "kept** in the denominator and" in readme or "kept in the denominator" in readme, (
        "the README no longer states which way the absent gold file is counted"
    )
    assert "excluded rather than counted as a retrieval" not in readme, (
        "the README states the exclusion rule again; `evaluate.py` mandates the opposite"
    )
    assert "denominator is\n154 and not 153" in readme or "154 and not 153" in readme


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


#: Reply shapes a model actually produces, against the single path each one names.
#:
#: The parser used to strip backticks and nothing else, then require the whole line to
#: be a path with no space in it. Every shape marked below with its old result was not
#: merely dropped - `resolve` left it unchanged and `fabrication_rate` counted it as a
#: named path absent from the repository. The arm was charged with inventing a file in
#: each case where the truth is that this harness could not read its answer, which is
#: the one direction of error a fabrication figure must not have.
SHAPES = {
    "bare": "django/db/models/query.py",
    "numbered": "1. django/db/models/query.py",
    "bulleted": "- django/db/models/query.py",
    "backticked": "`django/db/models/query.py`",
    "numbered and backticked": "1. `django/db/models/query.py`",
    # was "**django/db/models/query.py**" -> a fabrication
    "bold": "**django/db/models/query.py**",
    "bold bullet": "- **django/db/models/query.py**",
    # was '"django/db/models/query.py"' -> a fabrication
    "double quoted": '"django/db/models/query.py"',
    "single quoted": "'django/db/models/query.py'",
    # was "django/db/models/query.py:112" -> a fabrication
    "with a line number": "django/db/models/query.py:112",
    "with line and column": "django/db/models/query.py:112:8",
    # was dropped for the space -> one fewer path ranked, a silent miss
    "with a trailing note": "django/db/models/query.py - the queryset",
    "with a parenthetical": "django/db/models/query.py (the queryset)",
    "cited in a sentence": "The fix belongs in django/db/models/query.py, near the top.",
    # was "django/db/models/query.py," -> a fabrication
    "comma separated list": "django/db/models/query.py, django/db/models/base.py",
    "a markdown link": "[the queryset](django/db/models/query.py)",
    "dot slash": "./django/db/models/query.py",
    "a leading slash": "/django/db/models/query.py",
}

#: Paths whose own shape the parser used to damage, which the table above cannot
#: express because every row of it is the same path.
#:
#: The first group is the `lstrip` bug: `str.lstrip` takes a character SET, so
#: `".github/scripts/x.py".lstrip("./")` was `"github/scripts/x.py"` - a path in no
#: listing, which `resolve` cannot recover (it matches on "/" + p) and
#: `fabrication_rate` then counts as an invented file. 463 of the 66,895 paths in
#: `data/trees` are dot-prefixed and 9 of those are Python.
#:
#: The second is the extension list, which was closed around source files: a Django
#: template or a translation catalogue named by a model fell out as unparsed - honestly
#: reported, but a silent recall miss. `.rst` is 6,002 paths of the committed listings
#: and `.po` 3,646.
EXACT_SHAPES = {
    ".github/scripts/label_title_regex.py": ".github/scripts/label_title_regex.py",
    ".circleci/fetch_doc_logs.py": ".circleci/fetch_doc_logs.py",
    ".pyinstaller/hooks/hook-sklearn.py": ".pyinstaller/hooks/hook-sklearn.py",
    "./django/db/models/query.py": "django/db/models/query.py",
    "/django/db/models/query.py": "django/db/models/query.py",
    "django/contrib/admin/templates/base.html": "django/contrib/admin/templates/base.html",
    "django/conf/locale/de/LC_MESSAGES/django.po": "django/conf/locale/de/LC_MESSAGES/django.po",
    "sklearn/utils/_cython_blas.pyx": "sklearn/utils/_cython_blas.pyx",
    "doc/whats_new/v1.0.rst": "doc/whats_new/v1.0.rst",
    "build_tools/circle/build_doc.sh": "build_tools/circle/build_doc.sh",
}


@pytest.mark.parametrize("written,expected", sorted(EXACT_SHAPES.items()))
def test_a_path_is_returned_as_the_path_it_is(written, expected):
    from apps._engine.locate_prompts import parse_paths

    assert parse_paths(written) == [expected], written


@pytest.mark.parametrize(
    "written", ["and/or the behaviour changed.", "Makefile", "assets/logo.png"]
)
def test_what_is_not_a_source_path_is_still_not_one(written):
    """Widening the extension list must not turn prose or a binary into a path. The
    binary and generated end of the list stays out, and no bug report names a `.png`
    as the file to edit."""
    from apps._engine.locate_prompts import dropped_lines, parse_paths

    assert parse_paths(written) == [], written
    assert len(dropped_lines(written)) == 1, written


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_reply_shape_yields_the_path_it_names(shape):
    from apps._engine.locate_prompts import parse_paths

    got = parse_paths(SHAPES[shape])
    assert got[0] == "django/db/models/query.py", (shape, got)


def test_a_markdown_link_does_not_also_yield_its_label():
    """The one shape holding two path-shaped tokens where only one is an answer.

    Reading the label as well as the target adds a bare `query.py`, which almost never
    exists at a repository root - a fabrication the parser would have invented.
    """
    from apps._engine.locate_prompts import parse_paths

    assert parse_paths("[query.py](django/db/models/query.py)") == ["django/db/models/query.py"]


def test_prose_contributes_nothing_and_is_reported_as_unread():
    """Two things that must not be confused, which is the whole point of the split.

    A line that names nothing is a parse failure, and a parse failure is a fact about
    this harness. `dropped_lines` is what makes it sayable; folding it into the
    fabrication count would state it as a fact about the model.
    """
    from apps._engine.locate_prompts import dropped_lines, parse_paths

    reply = "I cannot tell from this report.\nand/or the behaviour changed.\n"
    assert parse_paths(reply) == []
    assert dropped_lines(reply) == [
        "I cannot tell from this report.",
        "and/or the behaviour changed.",
    ]

    # A fence, a language tag and a blank line are not failures to read anything.
    fenced = "```python\ndjango/db/models/query.py\n```\n"
    assert parse_paths(fenced) == ["django/db/models/query.py"]
    assert dropped_lines(fenced) == []


def test_the_unparsed_count_reaches_the_fabrication_report():
    """It has to be visible, or a parser that drops what it cannot read looks perfect.

    `rate_exists` rises when unreadable answers vanish. The count is carried per row so
    the two numbers sit side by side and neither can stand in for the other.
    """
    from apps._engine.evaluate import fabrication_rate

    rows = [
        {"repo": "r", "ranked": ["a.py", "nope.py"], "retriever": "llm", "unparsed": 3},
        {"repo": "r", "ranked": ["a.py"], "retriever": "llm", "unparsed": 0},
    ]
    found = fabrication_rate(rows, {"r": ["a.py", "b.py"]})
    assert found["paths_named"] == 3
    assert found["paths_that_exist"] == 2
    assert found["lines_unparsed"] == 3
    # And a row without the key reads as zero rather than crashing: the lexical arms
    # never parse a reply and do not carry one.
    bare = fabrication_rate([{"repo": "r", "ranked": ["a.py"]}], {"r": ["a.py"]})
    assert bare["lines_unparsed"] == 0


#: Reranker replies. The old parser read the first number in every line, one per line.
RERANK = {
    # was [c2] - two of the three picks thrown away
    "comma separated": ("3, 7, 12", ["c2", "c6", "c11"]),
    "space separated": ("3 7 12", ["c2", "c6", "c11"]),
    "one per line": ("3\n7\n12", ["c2", "c6", "c11"]),
    # was [c0, c2, c1, c6] - the list positions read as picks, ahead of the answers
    "numbered lines": ("1. 3\n2. 7", ["c2", "c6"]),
    # was [c9, c2, c6] - the restated instruction picked candidate 10 first
    "after restating the prompt": ("Here are the top 10 candidates:\n3\n7", ["c2", "c6"]),
    # was [c9, c3]
    "a count on the answer line": ("Choose the 10 best: 4", ["c3"]),
    "a sentence": ("I choose numbers 2 and 5.", ["c1", "c4"]),
    "prose with no numbers": ("I cannot tell.", []),
    "out of range": ("99\n3", ["c2"]),
}


@pytest.mark.parametrize("shape", sorted(RERANK))
def test_every_reranker_reply_shape_yields_the_choices_it_names(shape):
    from apps._engine.locate_prompts import parse_choices

    reply, expected = RERANK[shape]
    pool = [f"c{i}" for i in range(20)]
    assert parse_choices(reply, pool) == expected, shape


def test_an_out_of_range_number_is_ignored_rather_than_clamped():
    """A reranker choosing from a list cannot fabricate. Clamping to the ends would
    invent a choice it did not make, and the gap between this arm and the free one is
    the measurement - so a free guess here would close it by construction."""
    from apps._engine.locate_prompts import parse_choices

    pool = ["a.py", "b.py"]
    assert parse_choices("7", pool) == []
    assert parse_choices("0", pool) == []
    assert parse_choices("-1", pool) == ["a.py"], "the minus is not part of the number"


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
    """The fabrication figure must have a producer that runs.

    `evaluate.fabrication_rate` computes it and had no caller anywhere - the commit
    that composed the other four orphaned pieces left this one out, and `print_report`
    never printed it. So the README's claim had no producer in the repository that
    makes it. That claim ("one path in five") is now withdrawn on top of that, because
    the parser feeding this counted unreadable shapes as invented paths; the driver is
    asserted here so the replacement figure cannot be quoted without one.
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
