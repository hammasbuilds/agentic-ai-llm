"""What the command line does with a file that is not delimited text.

Both shapes here were found by an independent review driving the CLI, and neither was
reachable from the existing tests: the CLI is otherwise exercised only from
`test_real_corpus.py`, which skips without `CSV_CORPUS` - nine of this package's tests
skip on a fresh clone and the CLI's error paths were among them.

The two failures are the same mistake at opposite ends. A NUL in a header reached
sqlite and came back as `sqlite3.ProgrammingError: the query contains a null
character`, a traceback from the storage layer about a file the reader had just named.
A PNG did not fail at all: the latin-1 fallback decodes any byte sequence whatsoever,
so it was profiled as "2 rows and 1 columns (1 text), delimiter ',', read as latin-1"
beneath the footer "Every figure above was computed by a query that ran and passed
validation. No number here was written by a language model." Both sentences were true.
The file was an image.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from csvanalyst.cli import main
from csvanalyst.profile import NotDelimitedTextError, profile_csv


def test_a_nul_in_the_header_is_refused_not_a_traceback(tmp_path: Path, capsys):
    bad = tmp_path / "nul.csv"
    bad.write_bytes(b"a\x00b,c\n1,2\n")
    assert main(["report", str(bad)]) == 2
    captured = capsys.readouterr()
    assert "NUL byte in its header" in captured.err, captured.err
    assert "Traceback" not in captured.err
    assert "rows and" not in captured.out, captured.out


def test_a_binary_file_is_refused_rather_than_profiled(tmp_path: Path, capsys):
    png = tmp_path / "image.csv"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00")
    assert main(["report", str(png)]) == 2
    captured = capsys.readouterr()
    assert "not delimited text" in captured.err, captured.err
    assert "in its contents" in captured.err
    assert "rows and" not in captured.out, captured.out


def test_the_refusal_is_raised_by_the_reader_not_the_cli(tmp_path: Path):
    """So every caller gets it, not just `report`.

    `charts`, `impact` and `coercion` all go through `profile_csv` too, and a check
    that lived in one subcommand would leave the others reporting on an image.
    """
    png = tmp_path / "image.csv"
    png.write_bytes(b"\x00\x01\x02")
    try:
        profile_csv(png)
    except NotDelimitedTextError as exc:
        assert "NUL byte" in str(exc)
    else:  # pragma: no cover - the assertion is the test
        raise AssertionError("profile_csv accepted a binary file")


def test_a_real_csv_with_high_bytes_still_reads(tmp_path: Path, capsys):
    """The latin-1 fallback is deliberate and must survive the refusal.

    The rule is a NUL byte, not "any byte that is not utf-8" - real exports are not
    always utf-8, and failing on one in row 40,000 is the behaviour that fallback
    exists to avoid.
    """
    latin = tmp_path / "names.csv"
    latin.write_bytes("name,n\nM\xfcller,3\nS\xe3o,4\n".encode("latin-1"))
    assert main(["report", str(latin)]) == 0
    out = capsys.readouterr().out
    assert "latin-1" in out, out
    assert "2 rows" in out, out


def test_the_sweep_names_a_binary_file_rather_than_dropping_it(tmp_path: Path, capsys):
    """A sweep whose denominator quietly shrinks is the defect this whole tool is
    about, so a file it cannot read is counted and named rather than ending the run."""
    (tmp_path / "good.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (tmp_path / "bad.csv").write_bytes(b"\x00\x01\x02binary\n")
    assert main(["sweep", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 file(s) could not be profiled" in out, out
    assert "bad.csv" in out, out


# -- a UTF-16 export is text -------------------------------------------------------
#
# The NUL-byte sniff refused one with the words "No CSV contains one", which an
# Excel "Unicode Text (*.txt)" export falsifies: it is UTF-16LE, it is full of NUL
# bytes, and it is one of the commonest CSV-ish files there is. A byte-order mark
# is a statement about the encoding, so the rule is now: decode what declares itself,
# refuse what has NULs and no mark.

#: The encoding names Python writes a byte-order mark for. `utf-16-le` and
#: `utf-16-be` are NOT among them: those write the bytes with no mark, so a file
#: encoded that way declares nothing and is correctly refused - which is what
#: `test_a_markless_wide_file_is_refused` below pins. Getting this wrong was the first
#: version of these tests, and the failure was the test's rather than the code's.
UTF16 = ("utf-16", "utf-32", "utf-8-sig")


@pytest.mark.parametrize("encoding", UTF16)
def test_a_csv_with_a_byte_order_mark_is_profiled_not_refused(tmp_path: Path, encoding, capsys):
    wide = tmp_path / "excel.csv"
    wide.write_bytes("a,b\nM\u00fcller,2\nS\u00e3o,4\n".encode(encoding))
    assert main(["report", str(wide)]) == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "2 rows and 2 columns" in out, out
    # The encoding it used is named, because "read as latin-1" is how a reader knows
    # a figure might be about mojibake.
    assert "read as" in out


def test_a_binary_file_with_no_mark_is_still_refused(tmp_path: Path, capsys):
    """The other half: widening this must not accept a PNG."""
    png = tmp_path / "image.csv"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert main(["report", str(png)]) == 2
    err = capsys.readouterr().err
    assert "no byte-order mark" in err, err
    # The sentence that was false.
    assert "No CSV contains one" not in err


def test_a_markless_wide_file_is_refused(tmp_path: Path, capsys):
    """UTF-16 with no byte-order mark is indistinguishable from a binary file.

    There is no way to tell `a,b` in UTF-16LE from two-byte binary data without
    guessing, and guessing is what the latin-1 fallback already does one layer up.
    So the line is drawn at the mark: a file that declares itself is decoded, one that
    does not and holds NULs is refused. Pinned because it is the boundary, and an
    implementation that "helpfully" sniffed for wide text would cross it.
    """
    bare = tmp_path / "bare.csv"
    bare.write_bytes("a,b\n1,2\n".encode("utf-16-le"))
    assert main(["report", str(bare)]) == 2
    assert "no byte-order mark" in capsys.readouterr().err
