"""Claims made by layout rather than by a sentence.

A heading saying "All ten, at a glance" above a table of seven is drift, and no
regex over sentences can see it: the number is in the heading, the noun is
absent, and the evidence is the table underneath.

The four exclusions below are not defensive coding. Each one was a real false
positive on a real README, and together they took the reported rate from an
unbelievable 81% to 14%.
"""

from pathlib import Path

import pytest

from driftwatch.repos import ROOT, scan
from driftwatch.structure import broken_headings, counted_headings


def test_a_heading_is_checked_against_the_table_beneath_it():
    md = (
        "## All ten, at a glance\n\n"
        "| # | Project |\n|---|---|\n"
        "| 01 | a |\n| 02 | b |\n| 03 | c |\n"
    )
    (found,) = counted_headings(md)
    assert found.stated == 10
    assert found.found == 3
    assert found.kind == "table"
    assert not found.holds


def test_a_correct_heading_holds():
    md = "## The three places it can stop\n\n- a\n- b\n- c\n"
    (found,) = counted_headings(md)
    assert found.holds


def test_a_spelled_out_number_counts():
    md = "## Seven things worth measuring\n\n- a\n- b\n"
    assert counted_headings(md)[0].stated == 7


def test_a_multi_line_list_item_is_one_item():
    # This counted a three-item list as one, and reported a correct README as
    # drifted. Continuation lines are indented and belong to the item above.
    md = (
        "## Three bugs the tests caught\n\n"
        "1. **The parse tree consumed every token.** `service alpha`\n"
        "   and `service beta` could never reach the same leaf.\n"
        "2. **A constant series lost its sign** so an outage read\n"
        "   as a spike.\n"
        "3. **The third one.**\n"
    )
    (found,) = counted_headings(md)
    assert found.found == 3
    assert found.holds


def test_a_section_index_is_not_a_count():
    # "04 · The injection that isn't an instruction" is a section number.
    assert counted_headings("## 04 - The injection\n\n- a\n- b\n- c\n") == []
    assert counted_headings("## 4. Consent and purpose\n\n- a\n") == []


def test_a_date_is_not_a_count():
    md = "## 2026-09-16 - three projects updated\n\n| a |\n|---|\n| x |\n"
    assert counted_headings(md) == []


def test_a_version_number_is_not_a_count():
    md = "## v2.4 release notes\n\n- a\n- b\n"
    assert counted_headings(md) == []


def test_a_ranking_is_not_a_count():
    md = "## Top 5 findings\n\n- a\n- b\n"
    assert counted_headings(md) == []


def test_a_fenced_code_block_is_not_a_heading():
    # A JSON line inside a fence was read as a heading, turning
    # '{"quote": "...12.4%"}' into a claim about twelve of something.
    md = (
        "## Notes\n\n"
        '```\n## All twelve, at a glance\n{"source": "x", "quote": "12.4"}\n```\n\n'
        "| a |\n|---|\n| x |\n"
    )
    assert counted_headings(md) == []


def test_the_one_real_drift_this_ever_caught():
    # THE FINDING, kept as evidence rather than as a live assertion.
    #
    # `code-llm-lab`'s README carried "## All ten, at a glance" above a table of
    # seven rows, through five commits. The excerpt in fixtures/ is that section,
    # copied verbatim out of commit 31b8c43 — a real drift in a real repository,
    # found by this checker.
    #
    # It is a fixture because the original has since been rewritten by hand and
    # the heading now reads "All seven". Asserting against the live file made
    # this suite depend on a third party's README staying broken, which is not a
    # property any test should rest on: it passed for the wrong reason while the
    # drift lasted, then failed for the wrong reason when someone fixed it.
    excerpt = (Path(__file__).parent / "fixtures/code_llm_lab_drift.md").read_text(
        encoding="utf-8"
    )
    (found,) = broken_headings(excerpt)
    assert (found.stated, found.found, found.kind) == (10, 7, "table")
    assert "heading says 10" in found.detail


@pytest.mark.skipif(not ROOT.exists(), reason="no checkouts under REPOS_ROOT")
def test_across_the_real_portfolio_the_rate_is_believable():
    # Six headings across 35 repositories state a count, and all six are right
    # now that the one drift has been fixed upstream. The number that matters is
    # the denominator: a checker that reported 81% wrong was reporting its own
    # false positives, and this asserts the rate stays believable rather than
    # asserting any particular repository is broken.
    repos = scan()
    stated = sum(len(counted_headings(r.readme)) for r in repos)
    wrong = sum(len(broken_headings(r.readme)) for r in repos)
    assert stated >= 5
    assert wrong / stated < 0.30


@pytest.mark.parametrize(
    "heading,found,kind",
    [
        # Twenty agents in ten rows, two across. Counting rows reported this
        # repository's own correct README as drifted - and a drift checker that
        # cries wolf about its author is worse than no checker.
        ("The twenty business agents", 20, "table"),
        # An ordinary one-across table is unaffected.
        ("The three findings", 3, "table"),
        # Three across.
        ("The six tools", 6, "table"),
    ],
)
def test_a_table_laid_out_several_across_counts_entities_not_rows(heading, found, kind):
    excerpt = (Path(__file__).parent / "fixtures/multi_column_roster.md").read_text(
        encoding="utf-8"
    )
    counted = {c.heading: c for c in counted_headings(excerpt)}
    assert heading in counted, f"{heading!r} was not read as a count at all"
    assert (counted[heading].found, counted[heading].kind) == (found, kind)
    assert counted[heading].holds


def test_a_correct_multi_column_readme_is_not_reported_as_drifted():
    excerpt = (Path(__file__).parent / "fixtures/multi_column_roster.md").read_text(
        encoding="utf-8"
    )
    assert broken_headings(excerpt) == []
