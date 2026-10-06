"""claims-floor against real versioned regulation, across six regulators.

`products/data/ecfr_title*.json` are eCFR version indexes for Titles 12, 21, 26,
29, 40 and 45 — Banks, Food & Drugs, Internal Revenue, Labor, Environment and
Public Welfare. 6,000 real section versions with the date each took effect.

Regulation stands in for insurance policy wordings because insurers do not
publish a machine-readable archive of superseded wordings. The structure is the
same — a document with a history, and a question about a date — and it is real,
which an invented archive would not be.

Every figure asserted here was produced by running this code over those files.
"""

import statistics
from collections import defaultdict
from datetime import date

import pytest

from claimsfloor.ecfr import (
    DATA,
    INDEX,
    TITLES,
    amended,
    history,
    in_force,
    latest,
    versions,
    wrong_version_rate,
)

pytestmark = pytest.mark.skipif(not INDEX.exists(), reason="eCFR index not on disk")


def title_file(title):
    return str(DATA / f"ecfr_title{title}.json")


def test_all_six_titles_load():
    assert len(versions()) == 6_000
    assert {v.title for v in versions()} == set(TITLES)
    assert len(history()) == 3_204


def test_the_bare_section_number_is_not_unique_across_titles():
    # THE BUG THIS AVOIDS. `1.1` is a real section in five of the six titles.
    # Keying a history on the bare number splices unrelated agencies' sections
    # into one timeline and reports amendments that never happened.
    by_bare = defaultdict(set)
    for v in versions():
        by_bare[v.identifier].add(v.title)
    collisions = {k: t for k, t in by_bare.items() if len(t) > 1}
    assert len(collisions) == 140
    assert by_bare["1.1"] == {12, 21, 29, 40, 45}

    # Keyed correctly there are 3,204 sections; keyed on the bare number, 3,029
    # — and the difference is not lost rows, it is 149 invented amendments.
    bare = defaultdict(list)
    for v in versions():
        bare[v.identifier].append(v)
    bare_amended = {k: r for k, r in bare.items() if len(r) > 1}
    invented = sum(len(r) for r in bare_amended.values()) - sum(
        len(r) for r in amended().values()
    )
    assert len(bare) == 3_029
    assert invented == 149


def test_sections_are_amended_repeatedly():
    assert len(amended()) == 1_342
    sizes = [len(v) for v in amended().values()]
    assert statistics.median(sizes) == 2
    assert max(sizes) == 26  # one section amended twenty-six times


def test_the_index_contains_same_day_duplicates():
    # Several sections carry two entries with the same amendment date. Picking
    # a test case without checking for that produced a spurious failure, so it
    # is recorded here rather than worked around silently.
    same_day = [
        s for s, rows in amended().items() if len({r.effective for r in rows}) < len(rows)
    ]
    assert same_day


def test_in_force_picks_the_version_that_was_current_on_the_date():
    section, rows = next(
        (s, r) for s, r in sorted(amended().items()) if r[0].effective < r[1].effective
    )
    first, second = rows[0], rows[1]
    # The day before the second amendment, the first is still in force.
    day_before = date.fromordinal(second.effective.toordinal() - 1)
    assert in_force(section, day_before).effective == first.effective
    assert in_force(section, second.effective).effective == second.effective


def test_a_date_before_any_version_has_no_answer():
    section, _ = next(iter(sorted(amended().items())))
    assert in_force(section, date(1900, 1, 1)) is None


def test_returning_the_current_text_is_wrong_half_the_time():
    # THE FINDING. For a section that has ever been amended, answering from the
    # current text answers a different question than the one asked, in 49% of
    # the cases where the date matters.
    rate, mismatches = wrong_version_rate()
    assert rate == pytest.approx(0.491, abs=0.02)
    assert len(mismatches) == 2_032


def test_the_rate_holds_across_regulators_but_varies_threefold():
    # Every one of the six is between a fifth and three quarters. The pooled
    # number is not an average of unlike things — but a single title is not the
    # number either. Tax amends least destructively, Environment most.
    rates = {t: wrong_version_rate(title_file(t))[0] for t in TITLES}
    assert min(rates.values()) == pytest.approx(0.209, abs=0.02)  # Title 26, tax
    assert max(rates.values()) == pytest.approx(0.743, abs=0.02)  # Title 40, EPA
    assert all(0.2 <= r <= 0.75 for r in rates.values())


def test_the_severity_is_what_one_title_got_wrong():
    # Measured on Title 29 alone the median staleness is 0.28 years, and the old
    # README explained it away as "most amendments are recent". It was a fact
    # about OSHA. Every other regulator's median is between 1.99 and 4.35 years,
    # and pooled it is 2.47. The rate generalised; the severity did not.
    labor = [m.years_out for m in wrong_version_rate(title_file(29))[1]]
    assert statistics.median(labor) < 0.5

    others = [
        statistics.median([m.years_out for m in wrong_version_rate(title_file(t))[1]])
        for t in TITLES
        if t != 29
    ]
    assert min(others) > 1.9
    assert statistics.median([m.years_out for m in wrong_version_rate()[1]]) == (
        pytest.approx(2.47, abs=0.2)
    )


def test_and_it_can_be_a_decade_out():
    _, mismatches = wrong_version_rate()
    gaps = [m.years_out for m in mismatches]
    assert max(gaps) == pytest.approx(10.0, abs=0.3)


def test_the_latest_version_is_not_the_answer_to_a_dated_question():
    section = next(
        s for s, rows in sorted(amended().items()) if rows[0].effective != rows[-1].effective
    )
    rows = history()[section]
    assert in_force(section, rows[0].effective).effective == rows[0].effective
    assert latest(section).effective == rows[-1].effective
    assert in_force(section, rows[0].effective) != latest(section)


def test_an_unknown_section_returns_nothing_rather_than_guessing():
    assert in_force("not-a-section", date(2020, 1, 1)) is None
    assert latest("not-a-section") is None


def test_a_missing_index_is_reported_rather_than_faked():
    from claimsfloor.ecfr import IndexMissingError

    with pytest.raises(IndexMissingError):
        versions(str(INDEX.parent / "nope.json"))
