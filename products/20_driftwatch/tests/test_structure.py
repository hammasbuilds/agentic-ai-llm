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
    # The number that matters is the denominator. A checker that reported 81%
    # wrong was reporting its own false positives, and this asserts the rate stays
    # believable rather than asserting any particular repository is broken.
    #
    # Measured across the portfolio: 25 headings read as counts, 11 of them
    # wrongly (0.440), and of the remaining 14 about half agreed only by accident
    # - "Result 3" happens to sit above a three-row table. After tightening,
    # 12 read as counts and none is wrong.
    #
    # The floor on `stated` is the important half: precision is trivial to reach
    # by counting nothing, so a run that finds fewer than ten counted headings in
    # this portfolio has lost recall and must fail here rather than look perfect.
    repos = scan()
    stated = sum(len(counted_headings(r.readme)) for r in repos)
    wrong = sum(len(broken_headings(r.readme)) for r in repos)
    assert stated >= 10, f"only {stated} headings read as counts; recall has regressed"
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


# Every heading in this fixture is copied from a real README in the portfolio, and
# every one was reported as drift. They were 11 of 25 counted headings - a checker
# wrong 44% of the time, which is a checker nobody should believe. The last entry
# is a real count and must still be read as one.
@pytest.mark.parametrize(
    "heading",
    [
        "Result 3 — the average is carried by four trivial cases",
        "Finding 5 in detail: how many reads reach the model",
        "There aren't 200 sources. There are about ten.",
        "F1 with 95% bootstrap CI",
        "Failure categories (web2md, all 3,975 pages)",
        "What it scores, on 47 questions with `qwen2.5-coder:14b`",
        "04 · The injection that isn't an instruction",
        "Top 5 findings",
        "2026-09-16 · qwen2.5-coder:14b added",
    ],
)
def test_a_number_that_counts_nothing_is_not_read_as_a_count(heading):
    excerpt = (Path(__file__).parent / "fixtures/false_positive_headings.md").read_text(
        encoding="utf-8"
    )
    counted = {c.heading: c for c in counted_headings(excerpt)}
    assert heading not in counted, f"{heading!r} was read as a count of {counted.get(heading)}"


def test_the_one_real_count_in_that_fixture_is_still_found():
    """The tightening must not have been achieved by counting nothing."""
    excerpt = (Path(__file__).parent / "fixtures/false_positive_headings.md").read_text(
        encoding="utf-8"
    )
    counted = {c.heading: c for c in counted_headings(excerpt)}
    assert "Six tabs" in counted
    assert counted["Six tabs"].holds
    # And this one, which was a false positive only because "5" was read out of
    # the model name - the word "three" in it is a real count of three items.
    assert counted["The model arm: qwen2.5-coder:14b under three prompt shapes"].stated == 3


def test_the_whole_fixture_reports_no_drift():
    excerpt = (Path(__file__).parent / "fixtures/false_positive_headings.md").read_text(
        encoding="utf-8"
    )
    assert broken_headings(excerpt) == []


@pytest.mark.parametrize(
    "heading,stated",
    [
        # A number inside a larger number or a model name is not a count.
        ("Failure categories (all 3,975 pages)", None),
        ("The model arm: qwen2.5-coder:14b", None),
        # ...while the plain forms still read.
        ("The twenty business agents", 20),
        ("Six tabs", 6),
        ("Four refusal conditions", 4),
        ("The three places it can stop safely", 3),
    ],
)
def test_the_number_a_heading_states(heading, stated):
    from driftwatch.structure import _is_a_count, _stated

    assert (_stated(heading) if _is_a_count(heading) else None) == stated
