"""revenue-desk's revert detection, measured on real edit history.

A revert here is a line that went A, then B, then back to A: one edit undoing
another, which is the same event `domain.detect_reverts` looks for on a deal
record.

**The finding is measured against a frozen survey**, not against this disk.
`fixtures/portfolio_survey.json` is one row per repository under REPOS_ROOT with
full history, taken on 2026-10-05: 74 repositories, 1,222 commits, 1.6M line
edits. The live corpus is the working disk of a machine several sessions commit
to, and every assertion that rested on it has now broken at least once —
`authored_reverts == 27` first, then the median revert gap, then the share of
repositories with no revert, then the rate band itself. Each break was a
property of the disk that afternoon rather than of the method, and widening a
band each time is not a measurement, it is a moving target.

So the finding is pinned to data, the live corpus gets one smoke test that the
tool still runs on it, and when the frozen numbers are to be refreshed the
fixture is regenerated deliberately.

The headline is not any rate. It is that **the rate is an order of magnitude too
high unless you first decide what counts as an edit** — and getting that
decision right is this product's whole job on a CRM where agents and people
write into the same records.
"""

import json
import statistics
from pathlib import Path

import pytest

from revenue.churn import REPOS, Edit, find_reverts, is_authored, is_code, survey

FIXTURE = Path(__file__).parent / "fixtures/portfolio_survey.json"


@pytest.fixture(scope="module")
def frozen():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["repos"]


def rate(rows, numerator: str, denominator: str) -> float:
    edits = sum(r[denominator] for r in rows)
    return sum(r[numerator] for r in rows) / edits if edits else 0.0


# --- the finding ----------------------------------------------------------------------


def test_the_whole_portfolio_was_read(frozen):
    assert len(frozen) == 74
    assert sum(r["commits"] for r in frozen) == 1_222
    assert sum(r["edits"] for r in frozen) > 1_600_000
    assert all(r["commits"] > 0 for r in frozen)


def test_generated_files_are_most_of_the_edits_and_nearly_all_the_reverts(frozen):
    # THE FINDING. Committed datasets and regenerated `results.json` files are
    # 63% of every line edit in the portfolio — and 93% of every revert.
    #
    # The asymmetry is the point: generated files dominate the numerator far
    # more than the denominator, so leaving them in multiplies the answer.
    edits = sum(r["edits"] for r in frozen)
    reverts = sum(r["reverts"] for r in frozen)
    generated_edits = (edits - sum(r["authored_edits"] for r in frozen)) / edits
    generated_reverts = (reverts - sum(r["authored_reverts"] for r in frozen)) / reverts
    assert generated_edits == pytest.approx(0.632, abs=0.005)
    assert generated_reverts == pytest.approx(0.925, abs=0.005)
    assert generated_reverts > generated_edits * 1.4


#: The rate over source lines. Frozen reading: 46 reverts / 372,794 code edits.
#:
#: Roughly one revert per eight thousand lines of hand-written code. The naive
#: rate over the same history is 0.001155 — nine times this — so the distinction
#: the product rests on cannot slip through the band below.
CODE_RATE = (0.00007, 0.00018)


def test_the_rate_a_person_actually_produces(frozen):
    assert rate(frozen, "code_reverts", "code_edits") == pytest.approx(0.000123, abs=0.000005)
    low, high = CODE_RATE
    assert low < rate(frozen, "code_reverts", "code_edits") < high
    naive = rate(frozen, "reverts", "edits")
    assert naive / rate(frozen, "code_reverts", "code_edits") > 8


def test_authored_was_not_a_fine_enough_cut(frozen):
    """Why there is a third class, and not just "did a person type this".

    The authored rate more than doubled between surveys — 0.000101 across 36
    repositories, 0.000234 across 74 — and nobody started undoing their own work
    twice as often. 92 of the 138 authored reverts are prose: a README line
    returning verbatim while whole tables are rewritten in bulk is a line being
    restated, not one writer overruling another.

    `is_authored` separates a person from a script. It does not separate a
    decision from a restatement, and only code makes that distinction cleanly —
    a line of prose has no behaviour to undo. Once prose is out of the
    denominator the rate is 0.000123, inside the band measured at half the
    corpus size: the claim survived the portfolio doubling, which is the only
    reason to believe it.
    """
    code = rate(frozen, "code_reverts", "code_edits")
    prose_reverts = sum(r["authored_reverts"] - r["code_reverts"] for r in frozen)
    prose_edits = sum(r["authored_edits"] - r["code_edits"] for r in frozen)
    prose = prose_reverts / prose_edits
    assert prose == pytest.approx(0.000425, abs=0.00002)
    assert prose > code * 3


def test_a_convenience_cut_has_no_reliable_direction(frozen):
    # The old default stopped at 12 repositories in name order. That is not a
    # sample of anything, and the argument against it is not that it is biased
    # one way — it is that the direction is not stable. At 36 repositories the
    # subset understated the naive rate fivefold and OVERstated the authored
    # one; at 74 it understates both. A bias you cannot predict cannot be
    # reasoned about, only removed.
    twelve = frozen[:12]
    assert len(twelve) == 12
    assert rate(twelve, "reverts", "edits") < rate(frozen, "reverts", "edits") / 2
    assert rate(twelve, "code_reverts", "code_edits") < rate(
        frozen, "code_reverts", "code_edits"
    )


def test_most_repositories_contain_no_authored_revert_at_all(frozen):
    big = [r for r in frozen if r["code_edits"] > 1000]
    assert len(big) == 59
    clean = [r for r in big if not r["code_reverts"]]
    assert len(clean) == 42  # 0.712 of them


def test_no_real_revert_happens_within_a_single_commit(frozen):
    gaps = [g for r in frozen for g in r["code_gaps"]]
    assert len(gaps) == 46
    assert min(gaps) >= 1  # undoing is a relation between commits
    assert statistics.median(gaps) == 6  # and not usually the very next one
    assert max(gaps) == 44  # a few come back much later


# --- the live corpus ------------------------------------------------------------------


# A tree of checkouts, not merely a path that exists. The guard used to be
# `.exists()`, so an existing-but-empty REPOS_ROOT - a fresh clone on any other
# machine, or CI - ran these and FAILED instead of skipping, which is the loudest
# possible way to report that the corpus is absent.
@pytest.mark.skipif(
    not any(REPOS.glob("*/.git")), reason="REPOS_ROOT is not a tree of git checkouts"
)
def test_the_tool_still_runs_on_the_live_corpus():
    """That it reads a real disk at all. Deliberately the only live assertion.

    Wide bands and no claim about any particular repository: this exists to
    catch the tool breaking, not to re-measure the finding, and it is skipped
    wherever REPOS_ROOT is not a tree of checkouts — which is why the runner now
    reports skips instead of folding them into a total.
    """
    surveyed = survey(repos=5)
    assert 0 < len(surveyed) <= 5
    assert all(s.commits > 0 for s in surveyed)
    assert sum(s.edits for s in surveyed) > 0
    assert all(s.code_edits <= s.authored_edits <= s.edits for s in surveyed)


# --- the classifiers and the detector -------------------------------------------------


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


def test_only_source_carries_behaviour_to_undo():
    assert is_code("src/revenue/churn.py")
    assert is_code("scripts/build.sh")
    assert is_code("web/app.tsx")
    # Authored, and nothing in it can be reversed.
    assert not is_code("README.md")
    assert not is_code("pyproject.toml")
    assert not is_code("docs/design.md")
    # Not authored at all, so not code either.
    assert not is_code("results/metrics.json")
    assert not is_code("data/invoices.csv")


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


# --- the README is checked against the fixture it describes ---------------------------


def test_the_readme_quotes_this_fixture_and_not_an_older_survey(frozen):
    """Eleven numbers in this README were wrong against the fixture beside it.

    Every one came from an earlier, smaller survey, and nothing connected the prose to
    the data — so freezing the corpus fixed the tests and left the README describing a
    measurement the code no longer performs. A reader who checked would conclude the
    fixture had been backfilled to whatever the disk said.
    """
    # Whitespace-collapsed: the prose wraps, so "74 checkouts" is split across a line
    # break in the file and a literal search for it fails on a README that is correct.
    raw = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    readme = " ".join(raw.split())
    must_appear = [
        f"{len(frozen)} checkouts",
        f"{sum(r['commits'] for r in frozen):,} commits",
        f"{sum(r['edits'] for r in frozen):,} line edits",
        f"{sum(r['code_edits'] for r in frozen):,}",  # the code denominator
        f"{sum(r['code_reverts'] for r in frozen)} reverts in",  # the code numerator
    ]
    missing = [claim for claim in must_appear if claim not in readme]
    assert not missing, f"README does not quote the fixture: {missing}"

    # And the numbers from the survey this replaced must be gone.
    for stale in ("714,164", "267,192", "one in 9,896", "29 of the 35", "maximum 23"):
        assert stale not in readme, f"README still quotes the old survey: {stale}"


# --- the README's table, recomputed ----------------------------------------------------


def test_the_readme_table_is_what_the_fixture_says(frozen):
    """Every cell of the headline table, read back out of the README.

    The authored column carried 0.0425% — the prose rate, which appears correctly two
    paragraphs further down and is three and a half times larger. Nothing caught it,
    because the tests asserted each rate on its own and nobody asserted that the table
    printed the rate it was labelled with. A number in a README is a claim, and this is
    the fourth time one drifted from the code; the only fix that holds is to compute it.
    """
    import re

    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    row = {}
    for line in readme.splitlines():
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] in ("Line edits counted", "Reverts found", "Revert rate"):
            row[cells[0]] = cells[1:]
    assert set(row) == {"Line edits counted", "Reverts found", "Revert rate"}, row

    total = lambda key: sum(r[key] for r in frozen)  # noqa: E731
    columns = [("edits", "reverts"), ("authored_edits", "authored_reverts"), ("code_edits", "code_reverts")]
    for n, (edits, reverts) in enumerate(columns):
        assert row["Line edits counted"][n] == f"{total(edits):,}"
        assert row["Reverts found"][n] == f"{total(reverts):,}"
        assert row["Revert rate"][n] == f"{total(reverts) / total(edits):.4%}"

    # and the multiple quoted in the sentence under it
    ratio = (total("reverts") / total("edits")) / (total("code_reverts") / total("code_edits"))
    assert f"{ratio:.2f}\u00d7" in readme or f"{ratio:.2f}x" in readme
