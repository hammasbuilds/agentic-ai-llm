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
    text = (
        "Preamble here.\n\n1. Definitions\n\nWords mean things.\n\n"
        "2. Grant\n\nYou may use it.\n"
    )
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
    text = (
        "Apache License\n\n3. Grant of Patent License. "
        "Each Contributor grants you a patent licence."
    )
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


# Siblings of this repository, not `~/code`: that default does not exist on the


# machine these numbers were measured on, so every tool using it silently found


# nothing and reported success over an empty corpus.


CORPUS = Path(
    os.environ.get("REPOS_ROOT") or Path(__file__).resolve().parents[3].parent
).expanduser()


@pytest.mark.skipif(not CORPUS.exists(), reason="local checkout not present")
def test_the_python_licence_in_the_corpus_is_not_read_as_gpl():
    path = (
        CORPUS
        / "gan-diffusion-projects"
        / "pylibs"
        / "typing_extensions-4.16.0.dist-info"
        / "licenses"
        / "LICENSE"
    )
    if not path.is_file():
        pytest.skip("that package is not vendored here")
    reading = read(str(path), path.read_text(encoding="utf-8", errors="replace"))
    assert reading.family == "PSF"
    assert not reading.copyleft


# --- found by an independent review, which re-ran the survey -------------------------
#
# The README's headline no longer reproduced: 26 of 198 licence files came back
# unidentifiable and each one was reported as a conflict. Three separate causes, and
# none of them was the conflict rule - reporting an unidentifiable licence as a problem
# is the documented, conservative choice and it stays.


def fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")


def test_a_creative_commons_licence_is_identified():
    """Every CC file in the portfolio read as unknown, including the author's own.

    The CC licences open with "Creative Commons Corporation ... is not a law firm and
    does not provide legal services", so the FIRST occurrence of the name sits in a
    sentence carrying two context disqualifiers - guards written to stop the PSF
    licence being read as GPL because it mentions the GPL in a compatibility clause.
    Only that first occurrence was examined. Every occurrence is now considered, and a
    name used in the licence's own grant counts even when it also appears in a
    disclaimer.
    """
    reading = read("LICENSE", fixture("cc_by_4.txt"))
    assert reading.family == "CC"
    assert reading.family_citation is not None
    # And the sentence it grounded the claim in is not the disclaimer.
    assert "is not a law firm" not in reading.family_citation.sentence


def test_the_disqualifiers_still_stop_a_licence_being_misread():
    """The guard the fix had to preserve: a mention is not an adoption."""
    for sentence in (
        "This licence is compatible with the Apache License.",
        "This is not a Mozilla Public License.",
        "Unlike the Apache License, no patent grant is made.",
    ):
        assert read("LICENSE", sentence).family == "unknown"


def test_a_bare_copyright_notice_is_honestly_unidentifiable():
    """A grant is what makes a licence. This is the one file in the portfolio that
    still reads as unknown, and unknown is the right answer for it."""
    reading = read("LICENSE", fixture("bare_copyright.txt"))
    assert reading.family == "unknown"
    assert conflicts("MIT", reading) is not None


def test_a_documentation_page_is_not_a_licence_file(tmp_path: Path):
    """Sphinx and MkDocs ship docs/license.rst saying "see LICENSE in the root".

    Twelve of those were read as licence files, failed to identify, and were each
    reported as a conflict - in a tool whose stated first duty is not to cry wolf.
    """
    from contractreader.cli import _find

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "license.rst").write_text(fixture("docs_license_page.rst"), "utf-8")
    (tmp_path / "LICENSE").write_text("Permission is hereby granted, free of charge", "utf-8")
    found = [p.name for p in _find(tmp_path)]
    assert found == ["LICENSE"]


def test_a_virtualenv_is_skipped_by_its_marker_not_its_name(tmp_path: Path):
    """SKIP listed .venv and .venvs, so .venv-check was surveyed.

    The portfolio survey filled with third-party packages: 198 licence files where the
    README's measurement found 75. A name list cannot keep up with what people call
    their environments.
    """
    from contractreader.cli import _find

    env = tmp_path / ".venv-check" / "Lib" / "site-packages" / "thing"
    env.mkdir(parents=True)
    (tmp_path / ".venv-check" / "pyvenv.cfg").write_text("home = /usr\n", "utf-8")
    (env / "LICENSE").write_text("Permission is hereby granted, free of charge", "utf-8")
    (tmp_path / "LICENSE").write_text("Permission is hereby granted, free of charge", "utf-8")
    found = _find(tmp_path)
    assert [p.parent.name for p in found] == [tmp_path.name]


def test_the_readme_counts_the_tests_this_file_holds():
    """It said 27 while the file held 32, in two places.

    A count in a README is a claim, and this one moves every time a test is added -
    which is exactly when nobody rereads the README. Asked of pytest rather than
    counted with a regex, because `def test_` and parametrize cases are not the same
    number and the regex version of this test was wrong about its own file.
    """
    import re
    import subprocess
    import sys

    package = Path(__file__).resolve().parent.parent
    readme = (package / "README.md").read_text(encoding="utf-8")
    claimed = {int(n) for n in re.findall(r"(\d+) tests\b", readme)}
    assert claimed, "the README no longer states a test count"

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(package),
        capture_output=True,
        text=True,
        timeout=120,
    )
    found = re.search(r"(\d+) tests? collected", collected.stdout)
    assert found, collected.stdout[-500:]
    assert claimed == {int(found.group(1))}, (
        f"README says {sorted(claimed)}; pytest collects {found.group(1)}"
    )
