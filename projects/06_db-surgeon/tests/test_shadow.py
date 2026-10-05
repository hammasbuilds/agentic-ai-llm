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
