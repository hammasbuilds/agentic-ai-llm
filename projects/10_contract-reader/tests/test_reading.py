"""Tests for segmentation, span-grounding, and the context check.

The property that matters most is negative: a phrase found inside a sentence
that disclaims it must not become a finding. That is the rule the corpus
forced, and it has its own section below.
"""

from __future__ import annotations

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


# -- the PSF case, as a fixture rather than somebody else's vendored tree -----
#
# This was asserted against
# `<REPOS_ROOT>/gan-diffusion-projects/pylibs/typing_extensions-4.16.0.dist-info/
# licenses/LICENSE`, and skipped twice over: once because the root defaulted to
# `~/code`, and then - with REPOS_ROOT set - because that tree is gone, which this
# project's own README says. Two skips wearing a reason about local setup, and the
# headline case they were the only check on.
#
# The fixture is a real standalone PSF licence (pip's vendored `distlib`), copied in,
# so the evidence survives whatever happens to anybody else's checkout. That is the
# rule the three review causes below already follow.


def test_a_psf_licence_is_not_read_as_gpl():
    """The headline case: PSF text mentions the GPL, and is not copyleft.

    Section 3 of the PSF agreement discusses GPL compatibility, so a keyword matcher
    reading "GPL" and stopping finds exactly the wrong answer about the strictest
    thing a licence can say.
    """
    text = fixture("psf_licence.txt")
    assert "GPL" in text, "the fixture has to contain the word to be a test of anything"

    reading = read("psf_licence.txt", text)
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

    It used to require every count in the README to be the same number, which was
    true only while the package had one test file. A second file made the whole-suite
    figure and the per-file figure legitimately differ, and an assertion that they
    must match would have been satisfied by deleting the more informative of the two.
    So each claim is now checked against what it actually claims.
    """
    import re
    import subprocess
    import sys

    package = Path(__file__).resolve().parent.parent
    readme = (package / "README.md").read_text(encoding="utf-8")

    def collects(*target: str) -> int:
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--collect-only",
                "-p",
                "no:cacheprovider",
                *target,
            ],
            cwd=str(package),
            capture_output=True,
            text=True,
            timeout=300,
        )
        found = re.search(r"(\d+) tests? collected", done.stdout)
        assert found, done.stdout[-500:]
        return int(found.group(1))

    whole = re.search(r"pytest -q\s*#\s*(\d+) tests\b", readme)
    assert whole, "the README no longer states what the suite collects"
    assert int(whole.group(1)) == collects(), (
        f"README says {whole.group(1)} tests; pytest collects {collects()}"
    )

    per_file = re.findall(r"(tests/test_\w+\.py)\s+(\d+) tests\b", readme)
    assert per_file, "the layout block no longer counts the test files"
    for rel, stated in per_file:
        assert int(stated) == collects(rel), f"{rel}: README says {stated}"

    # Every test file is named, or a file could be added and counted nowhere.
    named = {rel for rel, _ in per_file}
    on_disk = {f"tests/{f.name}" for f in (package / "tests").glob("test_*.py")}
    assert named == on_disk, f"README names {sorted(named)}; on disk {sorted(on_disk)}"


def test_the_readme_states_one_unidentified_file_in_both_places():
    """It said one in the Results section and four in Scope, eighty lines apart.

    The four is the number of keyword matches the reader *rejects* as too weak to name
    a family - a different quantity from the files it ends up calling `unknown`, and
    the survey reports `unknown: 1` of 94.
    """
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    headline = re.search(r"\*\*(\w+) file in ninety-four is unidentifiable\*\*", readme)
    scope = re.search(r"\*\*`unknown` means unknown\.\*\* (\w+) file", readme)
    assert headline and scope, "the README no longer states both counts"
    assert headline.group(1).lower() == scope.group(1).lower() == "one"
