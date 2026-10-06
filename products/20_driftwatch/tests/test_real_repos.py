"""driftwatch against a folder of real repositories (REPOS_ROOT).

Real READMEs, real `pyproject.toml` files, real directory contents. Every figure
asserted here was produced by running this code over 35 real checkouts.

These assertions are about a working tree that changes, so they are written as
bands and properties rather than frozen counts wherever a count would rot. The
two that are exact are exact because they are the finding.
"""

import pytest

from driftwatch.domain import (
    MECHANICAL,
    NOT_CHECKABLE,
    Claim,
    broken,
    verifiable_share,
    verify,
)
from driftwatch.repos import ROOT, facts_for, scan, sentences

# A tree of checkouts, not merely a path that exists. The guard used to be
# `.exists()`, so an existing-but-empty REPOS_ROOT - a fresh clone on any other
# machine, or CI - ran these and FAILED instead of skipping, which is the loudest
# possible way to report that the corpus is absent.
pytestmark = pytest.mark.skipif(
    not any(ROOT.glob("*/.git")), reason="REPOS_ROOT is not a tree of git checkouts"
)


@pytest.fixture(scope="module")
def repos():
    return scan()


@pytest.fixture(scope="module")
def verdicts(repos):
    return [
        (repo, verify(claim, repo.facts))
        for repo in repos
        for claim in map(Claim, repo.claims)
        if claim.kind == MECHANICAL
    ]


def test_the_real_checkouts_are_found(repos):
    assert len(repos) >= 30
    names = {r.name for r in repos}
    assert {"rag-forge", "nlp-lab", "mcp-lab", "agentic-ai-lab"} <= names


def test_badges_and_code_blocks_are_not_claims():
    markdown = (
        "![tests](https://img.shields.io/badge/tests-376-success)\n"
        "```\nuv run pytest -q   # 376 passed\n```\n"
        "This project has 376 tests and they all pass.\n"
    )
    found = sentences(markdown)
    assert len(found) == 1
    assert found[0].startswith("This project has 376 tests")


def test_almost_nothing_in_a_readme_can_be_settled_by_a_machine(repos):
    # THE FINDING. 4,757 sentences across 35 repositories; fewer than two per
    # cent state something a checker can adjudicate. Doc-linting tools are built
    # as though this fraction were most of the file.
    claims = [Claim(c) for r in repos for c in r.claims]
    assert len(claims) > 4000
    share = verifiable_share(claims)
    assert 0.010 < share < 0.030


def test_a_third_of_even_those_have_no_fact_to_check_against(verdicts):
    checked = [v for _, v in verdicts if v.checked]
    assert 0.6 < len(checked) / len(verdicts) < 0.85


def test_roughly_one_in_ten_checkable_claims_is_false(verdicts):
    checked = [v for _, v in verdicts if v.checked]
    wrong = broken([v for _, v in verdicts])
    assert 0.03 < len(wrong) / len(checked) < 0.20


def test_the_flagship_zero_dependency_finding_was_not_drift(verdicts):
    """It was this product's headline example of drift caught live. It was wrong.

    `agentic-ai-lab`'s README says "In `projects/`. Zero runtime dependencies and
    zero LLM calls", and all eleven packages under that directory declare
    `dependencies = []`. The root declares thirteen for a web layer the sentence
    never mentions, and the checker compared the two. The sentence splitter had
    already cut "In `projects/`" off as its own sentence, so the scope was not even
    in the text being adjudicated.

    A repository whose sub-packages carry their own dependency lists cannot have a
    root-level claim like this settled from the root pyproject, so it is declined.
    """
    for repo, verdict in verdicts:
        if repo.name == "agentic-ai-lab" and "dependenc" in verdict.detail:
            assert not verdict.checked, verdict.detail
            assert "cannot be settled from the root pyproject alone" in verdict.detail


def test_a_zero_dependency_claim_is_still_checked_in_a_single_package_repo():
    """The check is not disabled: a repository of one package still gets adjudicated."""
    held = verify(
        Claim("Zero runtime dependencies."),
        {"root": ".", "dependencies": ["httpx>=0.27"], "sub_pyprojects": 0},
    )
    assert held.checked
    assert held.holds is False
    assert "httpx>=0.27" in held.detail

    clean = verify(
        Claim("Zero runtime dependencies."),
        {"root": ".", "dependencies": [], "sub_pyprojects": 0},
    )
    assert clean.checked
    assert clean.holds is True


def test_a_missing_referenced_file_is_caught(tmp_path):
    """Against a repository built here rather than somebody else's checkout.

    This asserted `RESULTS.md` in `rag-forge`, which the same sentence says `make
    eval` writes — a file the README tells you to generate is not a broken
    reference, and that one is now declined. The behaviour worth pinning is that a
    plainly-asserted missing file is still caught, and a fixture is the honest way
    to pin it.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    caught = verify(
        Claim("The evaluation table is in `RESULTS.md`."),
        {"root": str(tmp_path), "ignored": [], "sub_pyprojects": 0},
    )
    assert caught.checked
    assert caught.holds is False
    assert "RESULTS.md is missing" in caught.detail


def test_a_file_the_sentence_says_is_generated_is_not_a_broken_reference(tmp_path):
    declined = verify(
        Claim("Run `make eval` to generate `RESULTS.md`."),
        {"root": str(tmp_path), "ignored": [], "sub_pyprojects": 0},
    )
    assert not declined.checked
    assert "described as generated" in declined.detail


def test_a_gitignored_file_is_not_a_broken_reference(tmp_path):
    declined = verify(
        Claim("The corpus lives in `data/trials.json`."),
        {"root": str(tmp_path), "ignored": ["data/"], "sub_pyprojects": 0},
    )
    assert not declined.checked
    assert ".gitignore" in declined.detail


def test_a_path_named_as_somebody_elses_is_not_a_broken_reference(tmp_path):
    for sentence in (
        "About sixty lines of `sys.settrace`, not `coverage.py`.",
        "Django `runtests.py` produced seven logs.",
        "The Algebra zip contains `__MACOSX/._train.txt`.",
    ):
        declined = verify(
            Claim(sentence), {"root": str(tmp_path), "ignored": [], "sub_pyprojects": 0}
        )
        assert not declined.checked, sentence


def test_a_count_of_part_of_the_set_is_not_a_count_of_the_set():
    """Nine of the thirty claims reported false were this, and none was drift.

    "One project per LangGraph shape", "Two projects changed shape", "added to
    three projects" — each binds a number to the noun, and none states how many the
    repository has.
    """
    for sentence in (
        "One project per LangGraph shape, each built end to end.",
        "Two projects changed shape when the data was found.",
        "`qwen2.5-coder:14b` added to three projects.",
    ):
        declined = verify(Claim(sentence), {"project_count": 63})
        assert not declined.checked, sentence
        assert "part of the set" in declined.detail

    # "259 photographs, twelve per project" never reaches the count check at all:
    # neither noun is one this checker collects, so it is unfalsifiable earlier.
    # Worth stating, because it used to be reported as "README says 2, found 63" -
    # the number came from "Two projects changed shape" in the same sentence.
    earlier = verify(Claim("259 photographs, twelve per project."), {"project_count": 63})
    assert not earlier.checked
    assert earlier.detail == NOT_CHECKABLE

    counted = verify(
        Claim("57 projects spanning 14 algorithm families."), {"project_count": 63}
    )
    assert counted.checked
    assert counted.holds is False


def test_pycache_is_not_a_project(tmp_path):
    """It was counted as one, which reported langchain-lab as six against its five."""
    projects = tmp_path / "projects"
    for name in ("p01_a", "p02_b", "__pycache__", ".ipynb_checkpoints"):
        (projects / name).mkdir(parents=True)
    assert facts_for(tmp_path)["project_count"] == 2


def test_a_standard_library_module_is_not_a_declared_dependency():
    declined = verify(
        Claim("It has no runtime dependencies (the DOM is built on `html.parser`)."),
        {"dependencies": []},
    )
    assert not declined.checked
    assert "standard library" in declined.detail


def test_an_unfalsifiable_sentence_is_reported_not_rewritten():
    verdict = verify(Claim("The design is deliberately boring."), {"root": str(ROOT)})
    assert not verdict.checked
    assert verdict.holds is None


def test_facts_are_collected_not_inferred():
    facts = facts_for(ROOT / "rag-forge")
    assert facts["name"] == "rag-forge"
    assert "root" in facts
    assert isinstance(facts["python_files"], int)


def test_a_count_claim_is_checked_against_what_is_there():
    facts = {"project_count": 11, "root": str(ROOT)}
    assert verify(Claim("Eleven standalone tools, 11 projects in all."), facts).holds
    assert verify(Claim("There are 20 projects here."), facts).holds is False
