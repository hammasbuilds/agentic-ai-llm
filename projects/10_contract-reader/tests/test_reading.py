"""Tests for segmentation, span-grounding, and the context check.

The property that matters most is negative: a phrase found inside a sentence
that disclaims it must not become a finding. That is the rule the corpus
forced, and it has its own section below.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from contractreader.obligations import (
    ATTRIBUTION,
    DISCLOSE_SOURCE,
    NO_WARRANTY,
    PATENT_GRANT,
    conflicts,
    read,
)
from contractreader.segment import locate, normalise, segment

MIT = """MIT License

Copyright (c) 2026 Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software, to deal in the Software without restriction.

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. IN NO EVENT
SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM.
"""


# -- segmentation ----------------------------------------------------------


def test_a_document_with_no_headings_is_one_clause():
    """MIT has no numbered sections; inventing them would misplace citations."""
    clauses = segment(MIT)
    assert len(clauses) == 1
    assert clauses[0].heading == "(whole document)"


def test_numbered_headings_split_into_clauses():
    text = "Preamble here.\n\n1. Definitions\n\nWords mean things.\n\n2. Grant\n\nYou may use it.\n"
    headings = [c.heading for c in segment(text)]
    assert "1. Definitions" in headings
    assert "2. Grant" in headings


def test_clause_offsets_point_at_the_real_text():
    text = "1. Definitions\n\nWords mean things here.\n\n2. Grant\n\nYou may use it.\n"
    for clause in segment(text):
        assert text[clause.start : clause.end] == clause.text


def test_an_empty_document_yields_no_clauses():
    assert segment("   \n  ") == []


def test_normalise_joins_hard_wrapped_lines():
    """Licences wrap at 70 columns, so no phrase matches across the break."""
    wrapped = "Permission is hereby granted, free of\ncharge, to any person."
    assert "granted, free of charge" in normalise(wrapped)


def test_normalise_keeps_paragraphs_apart():
    assert "\n\n" in normalise("First para.\n\nSecond para.")


# -- span grounding --------------------------------------------------------


def test_locate_returns_exact_offsets():
    span = locate(MIT, "above copyright notice")
    assert span is not None
    assert MIT[span[0] : span[1]] == "above copyright notice"


def test_locate_tolerates_whitespace_differences():
    assert locate("granted,  free\nof   charge", "granted, free of charge") is not None


def test_locate_returns_none_when_absent():
    assert locate(MIT, "you must publish your source") is None


def test_every_finding_carries_a_span_that_resolves():
    """An ungrounded claim is the thing this package exists to prevent."""
    reading = read("LICENSE", MIT)
    normalised = normalise(MIT).lower()
    assert reading.findings
    for finding in reading.findings:
        c = finding.citation
        assert c.start >= 0
        assert normalised[c.start : c.end] == c.phrase


# -- reading a real MIT licence -------------------------------------------


def test_mit_is_identified():
    assert read("LICENSE", MIT).family == "MIT"


def test_mit_obligations_are_found():
    obligations = read("LICENSE", MIT).obligations
    assert ATTRIBUTION in obligations
    assert NO_WARRANTY in obligations


def test_mit_is_not_copyleft():
    assert not read("LICENSE", MIT).copyleft


def test_an_unidentifiable_document_is_unknown_not_guessed():
    assert read("LICENSE", "Some prose about nothing in particular.").family == "unknown"


# -- the context check: the reason this project exists --------------------


PSF_SHAPED = """B. TERMS AND CONDITIONS

1. This LICENSE AGREEMENT is between the Python Software Foundation and you.

2. PSF hereby grants you a licence to use the software.

8. Notwithstanding the foregoing, with regard to derivative works based on
Python 1.6.1 that incorporate non-separable material that was previously
distributed under the GNU General Public License (GPL), the law of the
Commonwealth of Virginia shall govern this License Agreement.
"""


def test_a_licence_naming_the_gpl_in_a_choice_of_law_clause_is_not_gpl():
    """The real misclassification this corpus produced.

    `typing_extensions` ships the Python licence, which names the GPL in a
    clause about Python 1.6.1 history. A keyword classifier reads the whole
    file as GPL and a compliance tool then raises a copyleft alarm that is
    not there.
    """
    reading = read("LICENSE", PSF_SHAPED)
    assert reading.family == "PSF"
    assert not reading.copyleft


def test_the_rejected_match_is_recorded_rather_than_hidden():
    reading = read("LICENSE", "This licence is compatible with the GNU General Public License.")
    assert reading.family != "GPL"
    assert any("GPL" in name for name, _ in reading.rejected)


def test_a_real_gpl_document_is_still_identified():
    """The context check must not defeat the true positive."""
    text = (
        "GNU GENERAL PUBLIC LICENSE\n\nThis program is free software. "
        "You must provide the source code to anyone who receives a binary."
    )
    reading = read("LICENSE", text)
    assert reading.family == "GPL"
    assert DISCLOSE_SOURCE in reading.obligations


@pytest.mark.parametrize(
    "sentence",
    [
        "This licence is compatible with the Apache License.",
        "This is not a Mozilla Public License.",
        "Unlike the Apache License, no patent grant is made.",
    ],
)
def test_phrases_inside_disclaiming_sentences_do_not_count(sentence: str):
    reading = read("LICENSE", sentence)
    assert reading.family == "unknown"


# -- obligations -----------------------------------------------------------


def test_apache_style_patent_grant_is_found():
    text = "Apache License\n\n3. Grant of Patent License. Each Contributor grants you a patent licence."
    reading = read("LICENSE", text)
    assert reading.family == "Apache-2.0"
    assert PATENT_GRANT in reading.obligations


def test_high_risk_obligations_are_separable():
    text = "You must provide the source code of any derived work."
    assert read("LICENSE", text).high_risk()


# -- compatibility ---------------------------------------------------------


def test_strong_copyleft_conflicts_with_a_permissive_project():
    reading = read("LICENSE", "GNU GENERAL PUBLIC LICENSE\n\nYou must provide the source code.")
    assert conflicts("MIT", reading)


def test_weak_copyleft_is_reported_as_file_level():
    reading = read("LICENSE", "Mozilla Public License Version 2.0\n\nTerms follow.")
    why = conflicts("MIT", reading)
    assert why and "file-level" in why


def test_permissive_inside_permissive_is_no_conflict():
    assert conflicts("MIT", read("LICENSE", MIT)) is None


def test_an_unidentified_licence_is_reported_as_a_conflict():
    """Unknown obligations are a compliance problem, not a pass."""
    why = conflicts("MIT", read("LICENSE", "Unreadable prose."))
    assert why and "could not be identified" in why


# -- against the real corpus ----------------------------------------------


CORPUS = Path(os.environ.get("REPOS_ROOT") or Path.home() / "code").expanduser()


@pytest.mark.skipif(not CORPUS.exists(), reason="local checkout not present")
def test_the_python_licence_in_the_corpus_is_not_read_as_gpl():
    path = (
        CORPUS / "gan-diffusion-projects" / "pylibs"
        / "typing_extensions-4.16.0.dist-info" / "licenses" / "LICENSE"
    )
    if not path.is_file():
        pytest.skip("that package is not vendored here")
    reading = read(str(path), path.read_text(encoding="utf-8", errors="replace"))
    assert reading.family == "PSF"
    assert not reading.copyleft
