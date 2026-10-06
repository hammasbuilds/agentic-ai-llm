"""bid-desk against real documents with real binding requirements.

`products/data/rfc*.txt` are published RFCs. RFC 2119 defines which words make a
requirement binding, and says they count only in upper case — so `MUST` is an
obligation and `must` in the same paragraph is prose. That is a labelled corpus
of mandatory, advisory and optional items with no annotation required.

Every figure asserted here was produced by running this code over those files.

The corpus grows: RFCs get added to `products/data/` as they become relevant,
and it has gone 6 -> 17 -> 24 documents. So the absolute counts below are
bands or relationships, never frozen totals. An earlier version pinned
`len(strict()) == 4_036` and five assertions like it, and every one of them
broke the moment a new RFC landed - which is the corpus improving, not the
extractor regressing.

What does NOT move is the precision of reading for the word instead of the
keyword: 0.830 over six documents, 0.827 over seventeen, 0.825 over
twenty-four. Quadrupling the corpus moved it by five thousandths. That is the
finding, and it is the thing worth pinning tightly.
"""

import pytest

from biddesk.rfc import (
    DATA,
    MANDATORY,
    _documents,
    by_keyword,
    compare_mandatory,
    loose,
    mandatory_only,
    strict,
)

pytestmark = pytest.mark.skipif(not list(DATA.glob("rfc*.txt")), reason="no RFC text on disk")


def test_the_documents_load():
    documents = len(list(DATA.glob("rfc*.txt")))
    assert documents >= 6, "too few RFCs on disk to measure anything"
    # A published RFC carries requirements in the hundreds; far below that and
    # the parser is dropping them, far above and it is matching prose.
    assert 100 * documents < len(strict()) < 400 * documents
    # The case-insensitive reader is a strict superset, always.
    assert len(loose()) > len(strict())


def test_the_keyword_mix_is_what_rfc_2119_describes():
    counts = by_keyword(strict())
    # MUST dominates: it is the word the standard tells authors to reach for.
    assert counts["MUST"] == max(counts.values())
    assert counts["MUST"] > len(strict()) * 0.3
    assert counts["SHALL"] < counts["MUST"] / 10  # rare now, and still binding
    assert set(counts) >= set(MANDATORY)


def test_mandatory_is_a_minority_of_all_requirements():
    requirements = strict()
    mandatory = mandatory_only(requirements)
    assert mandatory
    assert len(mandatory) < len(requirements)
    # Consistently a little over half: binding language outnumbers advisory,
    # but not overwhelmingly, and a swing outside this band would mean the
    # mandatory/advisory split had changed meaning.
    assert 0.45 < len(mandatory) / len(requirements) < 0.65


def test_a_case_insensitive_reader_cannot_miss_a_mandatory_item():
    # Upper case is a subset of case-insensitive, so recall is 1.0 by
    # construction. Worth asserting because it is the half everyone worries
    # about and it turns out not to be the problem.
    assert compare_mandatory().recall == 1.0


def test_but_one_flagged_obligation_in_five_is_not_one():
    # THE FINDING. 501 lines contain the word "must" without being requirements,
    # and a checklist built by reading for the word carries every one of them.
    #
    # Measured on six RFCs (0.830), then seventeen (0.827), now twenty-four (0.825).
    # Quadrupling the corpus moved it by five thousandths, which is the reason to
    # trust it.
    #
    # The band was `abs=0.015` - 0.812 through 0.842 - which is wide enough to hold
    # three different corpora, so the README went on saying 0.827 over "seventeen RFCs"
    # while `rfc._documents()` globbed twenty-four and this test said nothing. It is
    # `abs=0.002` now: tight enough that adding documents fails here, with the new
    # figure in the message, which is the moment to update the prose.
    result = compare_mandatory()
    assert result.precision == pytest.approx(0.825, abs=0.002), (
        f"precision is {result.precision:.4f} over {len(_documents())} documents; "
        "re-measure and update the README table"
    )
    # About one flagged obligation in five is not one. Asserted as a share
    # rather than a count, because the count tracks the corpus and the share
    # does not: 465 false positives over seventeen documents and 501 over the
    # twenty-four here, both close to a fifth of everything flagged.
    assert 0.15 < result.false_positives / result.found < 0.25


def test_the_distinction_is_the_capital_letters():
    # RFC 2119 is explicit that the keywords bind only in upper case, which is
    # exactly the signal a case-insensitive extractor throws away.
    upper = {(r.document, r.line) for r in mandatory_only(strict())}
    both = {(r.document, r.line) for r in mandatory_only(loose())}
    assert both - upper  # lines the loose reader added
    assert not upper - both  # and none it lost


def test_prohibitions_count_as_mandatory():
    counts = by_keyword(strict())
    assert counts["MUST NOT"] > 0
    # A prohibition is roughly a third as common as the obligation it mirrors.
    assert 0.2 < counts["MUST NOT"] / counts["MUST"] < 0.6
    assert all(r.mandatory for r in strict() if r.keyword == "MUST NOT")


def test_an_advisory_item_is_not_mandatory():
    should = [r for r in strict() if r.keyword == "SHOULD"]
    assert should
    assert not any(r.mandatory for r in should)


def test_missing_documents_are_reported_rather_than_faked():
    from biddesk.rfc import DocumentsMissingError

    with pytest.raises(DocumentsMissingError):
        strict(str(DATA / "nowhere"))


# -- the README's table against the measurement it quotes ---------------------


def test_every_row_of_the_readme_table_is_the_measured_value():
    """The test above pins the MEASUREMENT. Nothing pinned the README.

    So the table said "seventeen RFCs" and 4,036 / 2,242 / 5,750 / 0.827 / 465 while
    the tool globbed twenty-four documents and measured 4,304 / 2,389 / 6,143 / 0.825 /
    501 - and corrupting any single figure in the table left the suite green, because
    the only assertion about it was a band on the precision the code produces.
    """
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| ([^|]+?) \| \*{0,2}([\d.,]+)\*{0,2} \|$", readme, re.M))
    assert rows, "the README table no longer parses"

    comparison = compare_mandatory()
    mandatory = f"{len(mandatory_only(strict())):,}"
    expected = {
        "Requirements (RFC 2119, upper case)": f"{len(strict()):,}",
        "Of those, mandatory (`MUST`, `MUST NOT`, `SHALL`, `REQUIRED`)": mandatory,
        "What a case-insensitive reader finds": f"{len(loose()):,}",
        "**Recall on mandatory items**": f"{comparison.recall:.3f}",
        "**Precision**": f"{comparison.precision:.3f}",
        "**False positives**": f"{comparison.false_positives:,}",
    }
    for label, value in expected.items():
        assert label in rows, f"the table has no row for {label!r}: {sorted(rows)}"
        assert rows[label] == value, f"{label}: README says {rows[label]}, measured {value}"


def test_the_readme_names_the_corpus_size_it_measured():
    """The phrase "seventeen RFCs" survived four more documents being added."""
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    words = {17: "seventeen", 24: "twenty-four", 25: "twenty-five", 26: "twenty-six"}
    found = len(_documents())
    assert found in words, f"{found} documents; add the word to this test"
    assert words[found] in readme, (
        f"the README does not say {words[found]!r}, and there are {found} documents"
    )
    for wrong in set(words.values()) - {words[found]}:
        assert f"{wrong} RFCs" not in readme, f"the README still says {wrong!r}"
