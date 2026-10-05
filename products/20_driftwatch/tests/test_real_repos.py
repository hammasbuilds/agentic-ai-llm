"""driftwatch against a folder of real repositories (REPOS_ROOT).

Real READMEs, real `pyproject.toml` files, real directory contents. Every figure
asserted here was produced by running this code over 35 real checkouts.

These assertions are about a working tree that changes, so they are written as
bands and properties rather than frozen counts wherever a count would rot. The
two that are exact are exact because they are the finding.
"""

import pytest

from driftwatch.domain import MECHANICAL, Claim, broken, verifiable_share, verify
from driftwatch.repos import ROOT, facts_for, scan, sentences

# A tree of checkouts, not merely a path that exists. The guard used to be
# `.exists()`, so an existing-but-empty REPOS_ROOT - a fresh clone on any other
# machine, or CI - ran these and FAILED instead of skipping, which is the loudest
# possible way to report that the corpus is absent.
pytestmark = pytest.mark.skipif(
    not any(ROOT.glob('*/.git')), reason="REPOS_ROOT is not a tree of git checkouts"
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


def test_the_live_zero_dependency_drift_is_caught(verdicts):
    # agentic-ai-lab's README says zero runtime dependencies. Its pyproject now
    # declares fastapi, kafka, redis and langgraph among others.
    hits = [
        v for r, v in verdicts
        if r.name == "agentic-ai-lab" and v.checked and v.holds is False
    ]
    assert hits, "expected the zero-dependency claim to be caught"
    assert "zero dependencies" in hits[0].detail


def test_a_missing_referenced_file_is_caught(verdicts):
    missing = [
        v for _, v in verdicts
        if v.checked and v.holds is False and "missing" in v.detail
    ]
    assert missing
    assert any("RESULTS.md" in v.detail for v in missing)


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
