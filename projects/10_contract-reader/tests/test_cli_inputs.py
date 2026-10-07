"""What `read` does with a file that is not a licence.

An independent review pointed it at a `.csv` and got a report: "family: unknown,
1 clause(s)", an empty OBLIGATIONS table, exit 0. A PNG gave the same. An empty file
gave "0 clause(s)". None of those is a licence and all three read as a successful run.

The empty obligations table is the misleading part, and it is the same shape as every
other finding against this repository: a reader who passed the wrong path sees exactly
what a reader whose licence imposes no obligations sees. For a tool whose whole promise
is "cite the span behind every claim", answering about a file it found nothing in is
the one thing it cannot do.

`--anyway` is kept for the case where the empty reading is the thing you want, so the
refusal is a default rather than a wall.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contractreader.cli import main

MIT = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person "
    "obtaining a copy of this software, to deal in the Software without restriction, "
    "subject to the following conditions:\n\nThe above copyright notice and this "
    "permission notice shall be included in all copies.\n"
)


def test_a_csv_is_refused_rather_than_read_as_a_licence(tmp_path: Path, capsys):
    data = tmp_path / "data.csv"
    data.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
    assert main(["read", str(data)]) == 1
    captured = capsys.readouterr()
    assert "nothing here to cite" in captured.err, captured.err
    assert "OBLIGATIONS" not in captured.out, captured.out


def test_a_binary_file_is_refused_before_it_is_decoded(tmp_path: Path, capsys):
    """A distinct exit code from the one above, because it is a distinct answer: this
    file cannot be licence text, where a `.csv` merely is not."""
    binary = tmp_path / "image.txt"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert main(["read", str(binary)]) == 2
    assert "NUL byte" in capsys.readouterr().err


def test_an_empty_file_says_it_is_empty(tmp_path: Path, capsys):
    empty = tmp_path / "LICENSE"
    empty.write_text("", encoding="utf-8")
    assert main(["read", str(empty)]) == 2
    assert "is empty" in capsys.readouterr().err


def test_anyway_prints_the_empty_reading(tmp_path: Path, capsys):
    """The refusal is a default, not a wall: the empty reading is still reachable, and
    it still says on stderr that nothing was recognised."""
    data = tmp_path / "data.csv"
    data.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert main(["read", str(data), "--anyway"]) == 0
    captured = capsys.readouterr()
    assert "OBLIGATIONS" in captured.out, captured.out
    assert "nothing here to cite" in captured.err


def test_a_real_licence_still_reads(tmp_path: Path, capsys):
    """A refusal that refuses the working case is not a fix. MIT is recognised by
    family and cited, which is the whole output this tool exists to produce."""
    licence = tmp_path / "LICENSE"
    licence.write_text(MIT, encoding="utf-8")
    assert main(["read", str(licence)]) == 0
    out = capsys.readouterr().out
    assert "family: MIT" in out, out
    assert "permission is hereby granted" in out.lower()


def test_a_licence_with_no_obligations_is_not_confused_with_a_csv(tmp_path: Path, capsys):
    """The distinction the refusal has to preserve.

    A file whose family IS recognised has been read, whether or not it carries an
    obligation - so it prints, and exits 0. Only "no family AND no phrase AND nothing
    rejected" is the case where there was nothing to read.
    """
    licence = tmp_path / "LICENSE"
    licence.write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, to any person.\n",
        encoding="utf-8",
    )
    assert main(["read", str(licence)]) == 0
    assert "family: MIT" in capsys.readouterr().out


def test_a_missing_path_is_still_refused(tmp_path: Path, capsys):
    assert main(["read", str(tmp_path / "nope")]) == 2
    assert "not a file" in capsys.readouterr().err


# -- a UTF-16 export is text -------------------------------------------------------
#
# The NUL-byte sniff refused one with the words "No licence contains one", which an
# Excel "Unicode Text (*.txt)" export falsifies: it is UTF-16LE, it is full of NUL
# bytes, and it is one of the commonest licence-ish files there is. A byte-order mark
# is a statement about the encoding, so the rule is now: decode what declares itself,
# refuse what has NULs and no mark.

#: The encoding names Python writes a byte-order mark for. `utf-16-le` and
#: `utf-16-be` are NOT among them: those write the bytes with no mark, so a file
#: encoded that way declares nothing and is correctly refused - which is what
#: `test_a_markless_wide_file_is_refused` below pins. Getting this wrong was the first
#: version of these tests, and the failure was the test's rather than the code's.
UTF16 = ("utf-16", "utf-32", "utf-8-sig")


@pytest.mark.parametrize("encoding", UTF16)
def test_a_licence_with_a_byte_order_mark_is_read_not_refused(tmp_path: Path, encoding, capsys):
    wide = tmp_path / "LICENSE"
    wide.write_bytes(MIT.encode(encoding))
    assert main(["read", str(wide)]) == 0, capsys.readouterr().err
    assert "family: MIT" in capsys.readouterr().out


def test_a_binary_file_with_no_mark_is_still_refused(tmp_path: Path, capsys):
    png = tmp_path / "LICENSE"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert main(["read", str(png)]) == 2
    err = capsys.readouterr().err
    assert "no byte-order mark" in err, err
    assert "No licence contains one" not in err


def test_a_markless_wide_licence_is_refused(tmp_path: Path, capsys):
    """UTF-16 with no byte-order mark cannot be told from binary without guessing."""
    bare = tmp_path / "LICENSE"
    bare.write_bytes(MIT.encode("utf-16-le"))
    assert main(["read", str(bare)]) == 2
    assert "no byte-order mark" in capsys.readouterr().err
