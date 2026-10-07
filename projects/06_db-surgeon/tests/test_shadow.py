"""Round-trip tests. Every one executes real SQL on a real (in-memory) database."""

from __future__ import annotations

import pytest

from dbsurgeon.shadow import (
    MigrationFailed,
    apply,
    connect,
    round_trip,
    snapshot,
    split_statements,
)

SCHEMA = """
CREATE TABLE users (
    id       INTEGER PRIMARY KEY,
    email    TEXT NOT NULL,
    nickname TEXT
);
"""
SEED = """
INSERT INTO users (id, email, nickname) VALUES
    (1, 'a@x.com', 'ann'), (2, 'b@x.com', 'bob'), (3, 'c@x.com', NULL);
"""


# -- statement splitting --------------------------------------------------


def test_splits_on_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_a_semicolon_inside_a_string_is_not_a_separator():
    """`sql.split(';')` breaks on any default value containing one."""
    sql = "ALTER TABLE t ADD COLUMN c TEXT DEFAULT 'a;b'; SELECT 1;"
    assert split_statements(sql) == [
        "ALTER TABLE t ADD COLUMN c TEXT DEFAULT 'a;b'",
        "SELECT 1",
    ]


def test_line_comments_are_removed():
    assert split_statements("SELECT 1; -- drop everything\nSELECT 2;") == [
        "SELECT 1",
        "SELECT 2",
    ]


def test_block_comments_are_removed():
    assert split_statements("/* note; note */ SELECT 1;") == ["SELECT 1"]


def test_a_trigger_body_stays_one_statement():
    sql = "CREATE TRIGGER t AFTER INSERT ON users BEGIN UPDATE users SET nickname='x'; END;"
    assert len(split_statements(sql)) == 1


def test_a_trailing_statement_without_a_semicolon_is_kept():
    assert split_statements("SELECT 1") == ["SELECT 1"]


def test_an_escaped_quote_does_not_end_the_string():
    sql = "INSERT INTO t VALUES ('it''s; fine'); SELECT 1;"
    assert len(split_statements(sql)) == 2


# -- snapshots ------------------------------------------------------------


def test_snapshot_records_columns_and_rows():
    conn = connect(SCHEMA, SEED)
    snap = snapshot(conn)
    assert snap.table_names == {"users"}
    assert snap.tables["users"].column_names == ("id", "email", "nickname")
    assert snap.tables["users"].row_count == 3


def test_checksum_ignores_row_order():
    """A rebuild that re-inserts rows must not read as data loss."""
    a = connect(SCHEMA, "INSERT INTO users VALUES (1,'a',NULL),(2,'b',NULL);")
    b = connect(SCHEMA, "INSERT INTO users VALUES (2,'b',NULL),(1,'a',NULL);")
    assert snapshot(a).tables["users"].checksum == snapshot(b).tables["users"].checksum


def test_checksum_changes_when_a_value_changes():
    a = connect(SCHEMA, "INSERT INTO users VALUES (1,'a','x');")
    b = connect(SCHEMA, "INSERT INTO users VALUES (1,'a','y');")
    assert snapshot(a).tables["users"].checksum != snapshot(b).tables["users"].checksum


def test_null_is_distinguished_from_empty_string():
    a = connect(SCHEMA, "INSERT INTO users VALUES (1,'a',NULL);")
    b = connect(SCHEMA, "INSERT INTO users VALUES (1,'a','');")
    assert snapshot(a).tables["users"].checksum != snapshot(b).tables["users"].checksum


# -- the headline behaviour ----------------------------------------------


def test_dropping_a_column_restores_the_schema_and_loses_the_data():
    """The reason this project exists.

    The down-migration recreates the column, the column list matches as a
    set, and every value is gone. A review comparing schemas calls this
    reversible.
    """
    trip = round_trip(
        SCHEMA,
        SEED,
        "ALTER TABLE users DROP COLUMN nickname;",
        "ALTER TABLE users ADD COLUMN nickname TEXT;",
    )
    assert trip.schema_equivalent
    assert not trip.data_restored
    assert "users" in trip.changed_tables()


def test_a_re_added_middle_column_comes_back_at_the_end():
    """SQLite appends it. Anything relying on `SELECT *` ordering breaks.

    The dropped column has to be a middle one for this to show: re-adding a
    column that was already last happens to restore the original order, which
    is why the first version of this test passed against the wrong fixture.
    """
    schema = "CREATE TABLE t (id INTEGER PRIMARY KEY, middle TEXT, last TEXT);"
    seed = "INSERT INTO t VALUES (1,'m','l');"
    trip = round_trip(
        schema,
        seed,
        "ALTER TABLE t DROP COLUMN middle;",
        "ALTER TABLE t ADD COLUMN middle TEXT;",
    )
    assert trip.columns_reordered == ["t"]
    assert not trip.schema_restored  # order-sensitive
    assert trip.schema_equivalent  # order-insensitive
    assert trip.after_down.tables["t"].column_names == ("id", "last", "middle")


def test_re_adding_a_trailing_column_keeps_the_order():
    """The counterpart, so the reorder check is not just always true."""
    trip = round_trip(
        SCHEMA,
        SEED,
        "ALTER TABLE users DROP COLUMN nickname;",
        "ALTER TABLE users ADD COLUMN nickname TEXT;",
    )
    assert trip.columns_reordered == []
    assert trip.schema_restored
    assert not trip.data_restored  # the values are still gone


def test_a_genuine_round_trip_restores_both():
    trip = round_trip(
        SCHEMA,
        SEED,
        "ALTER TABLE users ADD COLUMN phone TEXT;",
        "ALTER TABLE users DROP COLUMN phone;",
    )
    assert trip.schema_restored
    assert trip.data_restored
    assert trip.verdict == "fully reversible"


def test_a_rename_round_trips_exactly():
    trip = round_trip(
        SCHEMA,
        SEED,
        "ALTER TABLE users RENAME COLUMN nickname TO display_name;",
        "ALTER TABLE users RENAME COLUMN display_name TO nickname;",
    )
    assert trip.schema_restored and trip.data_restored


def test_deleting_rows_is_reported_as_rows_lost():
    trip = round_trip(
        SCHEMA,
        SEED,
        "DELETE FROM users WHERE nickname IS NULL;",
        "-- nothing",
    )
    assert trip.rows_lost == 1
    assert not trip.data_restored


def test_dropping_a_table_is_not_restored_by_recreating_it():
    trip = round_trip(
        SCHEMA,
        SEED,
        "DROP TABLE users;",
        SCHEMA,
    )
    assert not trip.data_restored
    assert trip.rows_lost == 3


# -- failures -------------------------------------------------------------


def test_a_broken_statement_names_the_phase_and_the_sql():
    with pytest.raises(MigrationFailed) as excinfo:
        round_trip(SCHEMA, SEED, "ALTER TABLE nope DROP COLUMN x;", "-- none")
    assert excinfo.value.phase == "up"
    assert "nope" in excinfo.value.statement


def test_not_null_without_default_is_refused_by_the_engine():
    """Not a rule this tool invented - the database itself rejects it."""
    with pytest.raises(MigrationFailed):
        round_trip(SCHEMA, SEED, "ALTER TABLE users ADD COLUMN c TEXT NOT NULL;", "-- none")


def test_the_original_connection_is_rolled_back_on_failure():
    conn = connect(SCHEMA, SEED)
    with pytest.raises(MigrationFailed):
        apply(conn, "DELETE FROM users; SELECT bad_function();", "up")
    # The failed script must not leave half its work behind.
    assert snapshot(conn).tables["users"].row_count == 3


# -- the table and the count must use one definition ----------------------


def test_the_corpus_table_and_its_count_agree_on_what_schema_means(capsys):
    """They did not, and the disagreement was visible in one output.

    The `schema` column printed `schema_restored` - set equality AND original column
    order - while the summary counted `schema_equivalent`, which ignores order because
    that is what a schema-diff tool compares. So `drop an unused column` read `NO` in
    the table and was simultaneously one of the three in "3 match on schema and lose
    data". By the table's own column the answer was 2, which is the direction that
    flatters the thesis.
    """
    from dbsurgeon.cli import main

    assert main(["corpus"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()

    header = next(line for line in lines if line.startswith("migration"))
    assert "schema" in header and "order" in header and "data" in header

    # Parsed by column rather than sniffed for substrings: a first attempt matched
    # four rows because "ok" and "LOST" both appear on the `drop a lookup table` line,
    # whose schema column reads NO. Sniffing a fixed-width table is how a check ends
    # up with a denominator nobody chose.
    counted = int(
        next(line for line in lines if "match on schema and lose data" in line)
        .split(",")[-1]
        .strip()
        .split()[0]
    )
    assert counted == 3

    rows = []
    for line in lines:
        if (
            not line.startswith(" ")
            and len(line) > 60
            and not line.startswith(("migration", "-"))
        ):
            schema, order, data = line[36:44].strip(), line[44:51].strip(), line[51:58].strip()
            if schema in {"ok", "NO"}:
                rows.append((line[:36].strip(), schema, order, data))
    assert len(rows) == 10, [r[0] for r in rows]

    schema_ok_and_lost = [r for r in rows if r[1] == "ok" and r[3] == "LOST"]
    assert len(schema_ok_and_lost) == counted, (
        f"the summary counts {counted}; {len(schema_ok_and_lost)} rows show schema ok "
        f"and data LOST: {[r[0] for r in schema_ok_and_lost]}"
    )

    # And the reordered one is visible rather than folded into the schema column.
    moved = [line for line in lines if "MOVED" in line]
    assert len(moved) == 1
    assert "drop an unused column" in moved[0]
    assert "1 also moved a column" in out


def test_the_two_schema_properties_are_different_questions():
    """`schema_equivalent` is what a diff tool compares; `schema_restored` adds order."""
    import sys
    from pathlib import Path

    from dbsurgeon.plan import build

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migrations"))
    from corpus import CASES, SCHEMA, SEED  # type: ignore

    dropped = next(c for c in CASES if c[0] == "drop an unused column")
    trip = build(dropped[0], SCHEMA, SEED, dropped[1], dropped[2]).trip

    assert trip.schema_equivalent is True, "the column set came back"
    # Not a bool: it names the tables whose column order changed, which is why the
    # table can print MOVED and say which one.
    assert trip.columns_reordered == ["users"], trip.columns_reordered
    assert trip.schema_restored is False, "so the strict property is false"
    assert trip.data_restored is False


def test_the_run_it_annotations_describe_what_the_commands_print():
    """`corpus` was annotated "# the table above", and the table above it is the
    `check` output - a round-trip report for one migration, not a table at all.

    `scripts/sweep.py` is what produces the block the README shows, and the Layout
    section says so 70 lines further down. An annotation that points at the wrong
    command is the kind of thing a reader finds by running it, which is the one way of
    reading a README this repository is built around.
    """
    import re
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")

    annotation = re.search(r"^\$ db-surgeon corpus\s+#\s*(.+?)\s*$", readme, re.M)
    assert annotation, "the `corpus` Run-it line is gone; this test moved"
    assert "the table above" not in annotation.group(1), annotation.group(1)

    done = subprocess.run(
        [sys.executable, "-m", "dbsurgeon.cli", "corpus"],
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        env={"PYTHONPATH": "src", "PATH": __import__("os").environ.get("PATH", "")},
        timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    # The migration rows: everything above the `---` rule, minus the header. The
    # summary lines below the rule are not migrations, and counting them gave 14 where
    # the corpus holds 12 - the annotation this test replaced said "eleven", which was
    # my own count and also wrong.
    lines = done.stdout.splitlines()
    # Between the two rules. The FIRST `---` is the header's underline, so slicing to
    # it gave an empty list and the assertion below read `0 == 12`.
    rules = [i for i, line in enumerate(lines) if line.startswith("---")]
    assert len(rules) == 2, rules
    rows = [line for line in lines[rules[0] + 1 : rules[1]] if line.strip()]
    assert len(rows) == 12, (len(rows), rows)
    assert "twelve migrations" in annotation.group(1), annotation.group(1)
    # And the command's own summary agrees with the row count it printed.
    assert f"{len(rows)} migrations" in done.stdout, done.stdout[-300:]
