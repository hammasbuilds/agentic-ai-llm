"""A wrong argument should read as a wrong argument, not as a crash in the tool.

Every subcommand here takes a path to a file of SQL, and the argument `classify` takes
is named `sql` - so being handed the SQL itself is the mistake the command invites. It
answered with a fourteen-line `FileNotFoundError` traceback ending inside `pathlib.open`,
which buries the one fact that matters and looks like a bug in the tool.
"""

from __future__ import annotations

from dbsurgeon.cli import main


def test_sql_passed_instead_of_a_path_is_explained(capsys):
    code = main(["classify", "ALTER TABLE t ADD COLUMN added TEXT;"])
    captured = capsys.readouterr()
    assert code == 2
    assert "No such file" in captured.err
    assert "not SQL" in captured.err
    assert "Traceback" not in captured.err


def test_a_missing_file_is_named(capsys):
    code = main(["classify", "no_such_file.sql"])
    captured = capsys.readouterr()
    assert code == 2
    assert "no_such_file.sql" in captured.err


def test_a_real_script_still_classifies(tmp_path, capsys):
    """The other direction: the handler must not swallow a working run."""
    script = tmp_path / "up.sql"
    script.write_text("ALTER TABLE t ADD COLUMN added TEXT;\n", encoding="utf-8")
    code = main(["classify", str(script)])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.out.strip()
