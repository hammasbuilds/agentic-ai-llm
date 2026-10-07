"""What the command line does with a file that is not a text log.

Found by an independent review driving the CLI rather than the library. `templates`
pointed at a PNG reported "4 lines -> 4 templates (1.0x) at threshold 0.6, 0
template(s) merged distinct messages; 0 distinction(s) lost" - a complete report about
an image, compression ratio included, because `errors="replace"` decodes any byte
sequence at all. It then crashed printing its own output, since the replacement
characters it had just produced cannot be encoded by the Windows console, and that
crash was the only reason anybody noticed the report was nonsense.

Three failures, which this file keeps apart:

  * a binary file, reported on as though it were a log;
  * an empty file, a missing path and a directory with no logs in it, which all
    returned 2 with no output whatsoever - so a typo and an empty log were
    indistinguishable;
  * a character the console cannot encode, which ended a report halfway through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from detective.cli import main

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x02"
LOG = "2026-01-01 INFO started id=1\n2026-01-01 INFO started id=2\n"


def test_a_binary_file_is_refused_rather_than_reported_on(tmp_path: Path, capsys):
    binary = tmp_path / "image.log"
    binary.write_bytes(PNG)
    assert main(["templates", str(binary)]) == 2
    captured = capsys.readouterr()
    assert "not a text log" in captured.err, captured.err
    assert "templates" not in captured.out, captured.out


def test_every_command_refuses_it_because_the_reader_does(tmp_path: Path, capsys):
    """`cost` and `rare` read the same way, and a check in one command would leave
    the others reporting a compression ratio for an image."""
    binary = tmp_path / "image.log"
    binary.write_bytes(PNG)
    for command in ("templates", "cost", "rare"):
        assert main([command, str(binary)]) == 2, command
        assert "not a text log" in capsys.readouterr().err, command


def test_an_empty_file_says_it_is_empty(tmp_path: Path, capsys):
    """This was a bare `return 2` with no output at all."""
    empty = tmp_path / "quiet.log"
    empty.write_text("", encoding="utf-8")
    assert main(["templates", str(empty)]) == 2
    assert "is empty" in capsys.readouterr().err


def test_a_missing_path_says_so_rather_than_nothing(tmp_path: Path, capsys):
    assert main(["templates", str(tmp_path / "nope.log")]) == 2
    err = capsys.readouterr().err
    assert "no such path" in err, err


def test_a_directory_with_no_logs_says_so(tmp_path: Path, capsys):
    (tmp_path / "notes.txt").write_text("not a log\n", encoding="utf-8")
    assert main(["templates", str(tmp_path)]) == 2
    assert "no .log files" in capsys.readouterr().err


def test_one_binary_file_does_not_stop_a_directory_being_read(tmp_path: Path, capsys):
    """A directory is the normal argument, so one stray file must not end the run -
    and it must not disappear from the output either. A corpus that quietly shrinks is
    the failure this whole tool measures."""
    (tmp_path / "good.log").write_text(LOG, encoding="utf-8")
    (tmp_path / "image.log").write_bytes(PNG)
    assert main(["templates", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "not a text log, skipped: image.log" in captured.err, captured.err
    assert "2 lines" in captured.out, captured.out


def test_a_log_with_an_unencodable_character_is_still_reported(tmp_path: Path, capsys):
    """A real log can hold a character the console cannot encode. The report is about
    the log, so that character is worth a replacement glyph rather than a
    `UnicodeEncodeError` out of the middle of the output."""
    odd = tmp_path / "odd.log"
    odd.write_text("INFO start — id=1 �\nINFO start — id=2 �\n", encoding="utf-8")
    assert main(["templates", str(odd)]) == 0
    assert "2 lines" in capsys.readouterr().out


# -- a UTF-16 export is text -------------------------------------------------------
#
# The NUL-byte sniff refused one with the words "No log contains one", which an
# Excel "Unicode Text (*.txt)" export falsifies: it is UTF-16LE, it is full of NUL
# bytes, and it is one of the commonest log-ish files there is. A byte-order mark
# is a statement about the encoding, so the rule is now: decode what declares itself,
# refuse what has NULs and no mark.

#: The encoding names Python writes a byte-order mark for. `utf-16-le` and
#: `utf-16-be` are NOT among them: those write the bytes with no mark, so a file
#: encoded that way declares nothing and is correctly refused - which is what
#: `test_a_markless_wide_file_is_refused` below pins. Getting this wrong was the first
#: version of these tests, and the failure was the test's rather than the code's.
UTF16 = ("utf-16", "utf-32", "utf-8-sig")


@pytest.mark.parametrize("encoding", UTF16)
def test_a_log_with_a_byte_order_mark_is_read_not_skipped(tmp_path: Path, encoding, capsys):
    wide = tmp_path / "wide.log"
    wide.write_bytes("INFO start id=1\nINFO start id=2\n".encode(encoding))
    assert main(["templates", str(wide)]) == 0, capsys.readouterr().err
    assert "2 lines" in capsys.readouterr().out


def test_a_binary_log_with_no_mark_is_still_refused(tmp_path: Path, capsys):
    png = tmp_path / "image.log"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert main(["templates", str(png)]) == 2
    err = capsys.readouterr().err
    assert "no byte-order mark" in err, err
    assert "No log file contains one" not in err


def test_a_markless_wide_log_is_refused(tmp_path: Path, capsys):
    """UTF-16 with no byte-order mark cannot be told from binary without guessing."""
    bare = tmp_path / "bare.log"
    bare.write_bytes("INFO a\nINFO b\n".encode("utf-16-le"))
    assert main(["templates", str(bare)]) == 2
    assert "no byte-order mark" in capsys.readouterr().err
