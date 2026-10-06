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
    # THE FINDING. 465 lines contain the word "must" without being requirements,
    # and a checklist built by reading for the word carries every one of them.
    #
    # Measured first on six RFCs (precision 0.830) and again on seventeen
    # (0.827). Tripling the corpus moved it by three thousandths, which is the
    # reason to trust it.
    result = compare_mandatory()
    assert result.precision == pytest.approx(0.827, abs=0.015)
    # About one flagged obligation in five is not one. Asserted as a share
    # rather than a count, because the count tracks the corpus and the share
    # does not: 465 false positives over seventeen documents and 501 over
    # twenty-four, both close to a fifth of everything flagged.
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
