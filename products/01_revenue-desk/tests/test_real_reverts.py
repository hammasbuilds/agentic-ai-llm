"""revenue-desk's revert detection, measured on real edit history.

Every repository under REPOS_ROOT, full history — currently 36 of them, ~429
commits and ~714,000 line edits. A revert here is a line that went A, then B,
then back to A: one edit undoing another, which is the same event
`domain.detect_reverts` looks for on a deal record.

This is a live corpus. Commits keep landing in those checkouts, so the repository
count and the raw edit totals move between runs, and the assertions below are
bands wherever that is true.

The headline is not the rate anyway. It is that **the rate is an order of
magnitude too high unless you first decide what counts as an edit** — and that
is exactly the decision this product has to get right on a CRM where agents and
people write into the same records. The authored rate has now survived a 7.5 MB
dataset commit and a new repository appearing without moving at all.
"""

import statistics

import pytest

from revenue.churn import REPOS, Edit, find_reverts, is_authored, survey

pytestmark = pytest.mark.skipif(not REPOS.exists(), reason="no checkouts under REPOS_ROOT")


@pytest.fixture(scope="module")
def surveyed():
    return survey()  # no repo cap, full history


def totals(surveyed):
    return (
        sum(s.edits for s in surveyed),
        sum(len(s.reverts) for s in surveyed),
        sum(s.authored_edits for s in surveyed),
        sum(len(s.authored_reverts) for s in surveyed),
    )


def test_the_whole_portfolio_is_read(surveyed):
    # Bands, not equalities. This corpus is the working disk of a machine other
    # sessions also commit to, so the repository count and the raw edit total
    # move between runs — a 36th checkout appeared while this file was being
    # written. What must not move is the finding, and it does not: see
    # test_the_honest_rate_survives_a_dataset_commit.
    assert len(surveyed) >= 35
    assert sum(s.commits for s in surveyed) > 400
    assert sum(s.edits for s in surveyed) > 500_000
    assert all(s.commits > 0 for s in surveyed)


def test_taking_the_first_twelve_alphabetically_is_not_a_sample():
    # The old default stopped at 12 repositories in name order. That is not a
    # sample of anything: it reported 0.0237% against 0.1222% over all 35, a
    # fivefold undercount, because the repositories with the most regenerated
    # result files — mcp-lab and nlp-lab, 1,343 reverts between them — happen to
    # sort after the twelfth.
    #
    # Note which number that bias moves. The AUTHORED rate goes the other way:
    # 24 of the 27 hand-written reverts are in those first twelve, so the subset
    # slightly OVERstates it. A convenience cut has no reliable direction, which
    # is the argument against reasoning about its bias instead of removing it.
    twelve = survey(repos=12)
    everything = survey()
    assert len(twelve) == 12

    naive_part = sum(len(s.reverts) for s in twelve) / sum(s.edits for s in twelve)
    naive_full = sum(len(s.reverts) for s in everything) / sum(s.edits for s in everything)
    assert naive_part < naive_full / 4

    authored_part = sum(len(s.authored_reverts) for s in twelve) / sum(
        s.authored_edits for s in twelve
    )
    authored_full = sum(len(s.authored_reverts) for s in everything) / sum(
        s.authored_edits for s in everything
    )
    assert authored_part > authored_full


def test_generated_files_are_most_of_the_edits_and_nearly_all_the_reverts(surveyed):
    # THE FINDING. Committed datasets and regenerated `results.json` files are
    # most of every line edit in the portfolio — and 97% of every revert.
    #
    # The edit share is deliberately a wide band. It is not a constant: it moves
    # whenever anyone commits a dataset, and it did, mid-measurement — see
    # test_the_honest_rate_survives_a_dataset_commit. The *revert* share is the
    # stable half, and the asymmetry between them is the whole point: generated
    # files dominate the numerator far more than the denominator, so leaving
    # them in multiplies the answer.
    edits, reverts, authored_edits, authored_reverts = totals(surveyed)
    generated_edits = (edits - authored_edits) / edits
    generated_reverts = (reverts - authored_reverts) / reverts
    assert 0.5 < generated_edits < 0.8
    assert generated_reverts == pytest.approx(0.969, abs=0.03)
    assert generated_reverts > generated_edits * 1.4


#: The authored rate, observed across corpus sizes that differ by a third.
#:
#:   36 repos, ~264,000 authored edits, 27 reverts  ->  0.000101
#:   47 repos,  337,322 authored edits, 32 reverts  ->  0.000095
#:
#: Roughly one revert per ten thousand hand-written line edits. The band below
#: is wide enough to hold both readings and nothing else: the naive rate over
#: the same history is 0.001016, ten times the top of this range, so the
#: distinction the product rests on cannot slip through it.
AUTHORED_RATE = (0.00007, 0.00013)


def test_the_honest_rate_survives_a_dataset_commit(surveyed):
    # Committing one 7.5 MB GenBank corpus to this repository added ~127,000
    # line edits. The naive rate fell from 0.1489% to 0.1222% — an 18% swing
    # caused by no change in how anybody edits anything. The authored rate did
    # not move.
    #
    # That is the argument for the distinction, made by accident and kept.
    #
    # This asserted `authored_reverts == 27` and broke the moment anyone
    # committed anything, which on a live corpus is every day - the count is a
    # property of this disk on the afternoon it was written, not of the claim.
    # The claim is that the RATE holds while the corpus moves under it, and the
    # file's own docstring already said the assertions here are bands wherever
    # that is true. This one was not. It is now.
    _, _, authored_edits, authored_reverts = totals(surveyed)
    low, high = AUTHORED_RATE
    assert authored_edits > 250_000, "too little authored history to say anything"
    assert low < authored_reverts / authored_edits < high


def test_the_rate_a_person_actually_produces(surveyed):
    # Around one revert per ten thousand hand-written line edits. Git has diffs,
    # atomic commits and review, and this is the floor such a medium achieves.
    # The naive number over the same history is an order of magnitude higher,
    # and unlike this one it drifts with whatever was committed.
    edits, reverts, authored_edits, authored_reverts = totals(surveyed)
    low, high = AUTHORED_RATE
    assert low < authored_reverts / authored_edits < high
    assert (reverts / edits) / (authored_reverts / authored_edits) > 8


def test_a_results_file_is_not_authored():
    assert not is_authored("projects/03_bfcl/results.json")
    assert not is_authored("nlp-lab/projects/09/results/collocations.json")
    assert not is_authored("data/invoices.csv")
    assert not is_authored("uv.lock")
    assert is_authored("src/revenue/churn.py")
    assert is_authored("README.md")
    assert is_authored("pyproject.toml")
    # A hand-written config that merely lives beside results is still authored.
    assert is_authored("config/settings.json")


def test_most_repositories_contain_no_authored_revert_at_all(surveyed):
    big = [s for s in surveyed if s.authored_edits > 1000]
    assert len(big) >= 30
    clean = [s for s in big if not s.authored_reverts]
    assert len(clean) / len(big) > 0.75  # 29 of 35


def test_a_line_that_comes_back_verbatim_is_a_revert():
    history = [
        Edit("c1", 0, "a.py", "timeout = 30  # measured", added=True),
        Edit("c2", 1, "a.py", "timeout = 30  # measured", added=False),
        Edit("c2", 1, "a.py", "timeout = 90  # guessed", added=True),
        Edit("c3", 2, "a.py", "timeout = 90  # guessed", added=False),
        Edit("c3", 2, "a.py", "timeout = 30  # measured", added=True),
    ]
    (revert,) = find_reverts(history)
    assert revert.line.startswith("timeout = 30")
    assert revert.removed_at == 1
    assert revert.restored_at == 2


def test_a_line_removed_and_restored_inside_one_commit_is_not_a_revert():
    # It moved, or the same text appears in two hunks. With -U0 git reports that
    # as a remove/add pair, and counting it was 86% of everything this found.
    history = [
        Edit("c1", 0, "a.py", "timeout = 30  # measured", added=True),
        Edit("c2", 1, "a.py", "timeout = 30  # measured", added=False),
        Edit("c2", 1, "a.py", "timeout = 30  # measured", added=True),
    ]
    assert find_reverts(history) == []


def test_no_real_revert_happens_within_a_single_commit(surveyed):
    gaps = [r.gap for s in surveyed for r in s.authored_reverts]
    assert gaps
    assert min(gaps) >= 1  # undoing is a relation between commits
    assert statistics.median(gaps) == 1  # and usually the very next one
    assert max(gaps) > 5  # though a few come back much later


def test_a_rewrite_is_not_a_revert():
    history = [
        Edit("c1", 0, "a.py", "timeout = 30  # measured", added=True),
        Edit("c2", 1, "a.py", "timeout = 30  # measured", added=False),
        Edit("c2", 1, "a.py", "timeout = 45  # different again", added=True),
    ]
    assert find_reverts(history) == []


def test_trivial_lines_are_not_corrections():
    # A brace coming back is not someone's judgement being undone.
    history = [
        Edit("c1", 0, "a.py", "}", added=True),
        Edit("c2", 1, "a.py", "}", added=False),
        Edit("c3", 2, "a.py", "}", added=True),
    ]
    assert find_reverts(history) == []


def test_an_empty_history_yields_nothing():
    assert find_reverts([]) == []
