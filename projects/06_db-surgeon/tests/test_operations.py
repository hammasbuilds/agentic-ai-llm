"""Static classification tests, and the honest limits of pattern matching."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dbsurgeon.operations import BLOCKING, LOSSY, REVERSIBLE, classify, classify_script
from dbsurgeon.plan import NothingToCheckError, build, render

SCHEMA = "CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b INTEGER NOT NULL DEFAULT 0);"
SEED = "INSERT INTO t VALUES (1,'x',5),(2,'y',6),(3,NULL,7);"


@pytest.mark.parametrize(
    ("sql", "kind", "category"),
    [
        ("DROP TABLE users;", "drop_table", LOSSY),
        ("ALTER TABLE users DROP COLUMN nickname;", "drop_column", LOSSY),
        ("TRUNCATE TABLE users;", "truncate", LOSSY),
        ("DELETE FROM users;", "delete_all", LOSSY),
        ("UPDATE users SET a = 1;", "update", LOSSY),
        ("ALTER TABLE users RENAME COLUMN a TO b;", "rename", REVERSIBLE),
        ("ALTER TABLE users ADD COLUMN phone TEXT;", "add_column", REVERSIBLE),
        ("CREATE TABLE x (id INTEGER);", "create_table", REVERSIBLE),
        ("DROP INDEX idx_a;", "drop_index", REVERSIBLE),
        ("INSERT INTO users VALUES (1);", "insert", REVERSIBLE),
        ("CREATE INDEX idx_a ON users(a);", "create_index", BLOCKING),
        (
            "CREATE INDEX CONCURRENTLY idx_a ON users(a);",
            "create_index_concurrently",
            REVERSIBLE,
        ),
        (
            "ALTER TABLE users ADD COLUMN c TEXT NOT NULL;",
            "add_notnull_no_default",
            BLOCKING,
        ),
    ],
)
def test_statements_are_classified(sql: str, kind: str, category: str):
    op = classify(sql)
    assert op.kind == kind
    assert op.category == category


def test_add_notnull_with_a_default_is_not_blocking():
    op = classify("ALTER TABLE users ADD COLUMN c TEXT NOT NULL DEFAULT 'x';")
    assert op.kind == "add_column"
    assert op.category == REVERSIBLE


def test_targets_are_extracted():
    assert classify("DROP TABLE orders;").target == "orders"
    assert classify("CREATE INDEX idx_x ON t(a);").target == "idx_x"
    assert classify("ALTER TABLE users ADD COLUMN c TEXT;").target == "users"


def test_an_unrecognised_statement_is_unknown_not_guessed():
    op = classify("VACUUM;")
    assert op.category == "unknown"
    assert "round-trip is the authority" in op.reason


def test_a_script_classifies_every_statement():
    ops = classify_script("ALTER TABLE t ADD COLUMN c TEXT; DROP TABLE t;")
    assert [o.kind for o in ops] == ["add_column", "drop_table"]


# -- where the static rules are wrong, and the tool says so ---------------


def test_a_false_positive_is_reported_as_a_disagreement():
    """An UPDATE is flagged lossy, but this one restores the original values.

    The round-trip proves it and the disagreement is surfaced, because a
    pattern that mispredicts is a defect in this tool rather than something
    to hide behind a confident verdict.
    """
    plan = build(
        "idempotent update",
        SCHEMA,
        SEED,
        "UPDATE t SET a = LOWER(a);",
        "-- already lowercase",
    )
    assert plan.predicted_lossy
    assert plan.observed_lossy is False
    assert any("too pessimistic" in d for d in plan.disagreements)


def test_a_false_negative_is_reported_as_a_disagreement():
    """A qualified DELETE matches no lossy rule and still destroys rows."""
    plan = build(
        "qualified delete",
        SCHEMA,
        SEED,
        "DELETE FROM t WHERE b > 5;",
        "-- nothing to undo",
    )
    assert not plan.predicted_lossy
    assert plan.observed_lossy is True
    assert any("gap" in d for d in plan.disagreements)


def test_agreement_produces_no_disagreement():
    plan = build(
        "clean add",
        SCHEMA,
        SEED,
        "ALTER TABLE t ADD COLUMN c TEXT;",
        "ALTER TABLE t DROP COLUMN c;",
    )
    assert plan.disagreements == []
    assert plan.safe


def test_a_migration_that_cannot_run_is_reported_not_raised():
    plan = build("broken", SCHEMA, SEED, "ALTER TABLE nope DROP COLUMN x;", "-- none")
    assert plan.error is not None
    assert plan.verdict == "did not run"
    assert not plan.safe


# -- nothing to run is not a clean bill of health -----------------------------


@pytest.mark.parametrize(
    "up",
    ["", "   ", "\n\n", "-- TODO: write this", "-- one\n-- two\n", ";", ";;\n;", "\t;  \n"],
    ids=lambda s: repr(s)[:24],
)
def test_an_up_with_no_statements_is_refused_rather_than_called_reversible(up):
    """The one verdict this tool must never give by accident.

    An empty `up` produced "FULLY REVERSIBLE / schema restored: yes / data restored:
    yes" and exit 0 under `--strict`. Running nothing and reversing nothing does restore
    everything - it is true, and it is not an answer about a migration. A mistyped path,
    a file that failed to write, or `--up` pointing at the wrong extension each read as
    a clean bill of health from the tool whose premise is refusing unsafe migrations.

    Garbage SQL was handled correctly all along, so the gap was precisely between
    "could not run" and "nothing to run".
    """
    with pytest.raises(NothingToCheckError):
        build(name="m", schema=SCHEMA, seed="", up=up, down="")


def test_a_real_migration_is_still_checked():
    """A refusal that refuses everything is not a check."""
    plan = build(
        name="m",
        schema=SCHEMA,
        seed="INSERT INTO t (a) VALUES ('x');",
        up="ALTER TABLE t ADD COLUMN c TEXT;",
        down="ALTER TABLE t DROP COLUMN c;",
    )
    assert plan.safe is True
    assert plan.verdict.lower() == "fully reversible"


def test_an_empty_down_is_not_refused_because_it_is_a_real_finding():
    """Only `up` is required. A migration with no `down` is irreversible, and saying so
    IS the answer - refusing to look would hide it."""
    plan = build(
        name="m", schema=SCHEMA, seed="", up="ALTER TABLE t ADD COLUMN c TEXT;", down=""
    )
    assert plan.safe is False
    assert plan.verdict == "schema not restored"


# -- a comparison that only ran one way ---------------------------------------


def test_a_column_down_failed_to_drop_is_a_failed_reversal():
    """`schema_equivalent` checked only for things the round trip LOST.

    Its docstring says "same tables, same columns, same types", and it asked
    `missing_tables or columns_lost or types_changed` - nothing about what was ADDED.
    So `ALTER TABLE t ADD COLUMN c` with no `down` reported FULLY REVERSIBLE on a schema
    that still has `c`, and `--strict` exited 0. It is not cosmetic: the next `up` fails
    with "column already exists", so a migration called reversible cannot be re-applied.
    """
    plan = build(
        name="m", schema=SCHEMA, seed="", up="ALTER TABLE t ADD COLUMN c TEXT;", down=""
    )
    assert plan.trip is not None
    assert plan.trip.columns_added == ["t.c"]
    assert plan.trip.schema_equivalent is False
    assert plan.trip.schema_restored is False
    assert plan.safe is False


def test_a_table_down_failed_to_drop_is_the_same_failure():
    plan = build(name="m", schema=SCHEMA, seed="", up="CREATE TABLE u (id INTEGER);", down="")
    assert plan.trip.extra_tables == ["u"]
    assert plan.safe is False


def test_the_report_names_what_down_left_behind():
    """Printed, not only returned. Every line of this report described something lost."""
    plan = build(
        name="m", schema=SCHEMA, seed="", up="ALTER TABLE t ADD COLUMN c TEXT;", down=""
    )
    text = render(plan)
    assert "columns left    : t.c" in text, text
    assert "re-applying `up` will fail" in text, text


def test_a_clean_round_trip_reports_nothing_left_behind():
    """The symmetric check must not fire on a migration that really does reverse."""
    plan = build(
        name="m",
        schema=SCHEMA,
        seed="INSERT INTO t (a) VALUES ('x');",
        up="ALTER TABLE t ADD COLUMN c TEXT;",
        down="ALTER TABLE t DROP COLUMN c;",
    )
    assert plan.trip.columns_added == []
    assert plan.trip.extra_tables == []
    assert plan.safe is True
    assert "columns left" not in render(plan)


def test_columns_added_is_the_mirror_of_columns_lost():
    """Both directions over the same pair, so neither can be the only one implemented."""
    added = build(
        name="a", schema=SCHEMA, seed="", up="ALTER TABLE t ADD COLUMN c TEXT;", down=""
    ).trip
    lost = build(
        name="l",
        schema=SCHEMA,
        seed="",
        up="ALTER TABLE t DROP COLUMN a;",
        down="",
    ).trip
    assert (added.columns_added, added.columns_lost) == (["t.c"], [])
    assert (lost.columns_added, lost.columns_lost) == ([], ["t.a"])


def test_comments_do_not_count_as_statements():
    """`sql.strip()` is not enough: a file of `-- TODO` is as empty as an empty one, and
    an all-comments migration is the likeliest way to arrive here by accident."""
    from dbsurgeon.plan import _statements

    assert _statements("-- just a note") == []
    assert _statements("ALTER TABLE t ADD COLUMN b TEXT; -- why") == [
        "ALTER TABLE t ADD COLUMN b TEXT"
    ]
    assert (
        len(_statements("ALTER TABLE t ADD COLUMN b TEXT;\nALTER TABLE t DROP COLUMN a;")) == 2
    )


def test_the_cli_refuses_an_empty_migration_with_exit_two(tmp_path, capsys):
    """Exit 2, not 0 and not 1: it is neither a pass nor an unsafe migration."""
    from dbsurgeon.cli import main

    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA, encoding="utf-8")
    empty = tmp_path / "up.sql"
    empty.write_text("-- nothing yet\n", encoding="utf-8")
    down = tmp_path / "down.sql"
    down.write_text("ALTER TABLE t DROP COLUMN b;", encoding="utf-8")

    code = main(
        [
            "check",
            "--schema",
            str(schema),
            "--up",
            str(empty),
            "--down",
            str(down),
            "--strict",
        ]
    )
    assert code == 2
    out = capsys.readouterr()
    assert "nothing to check" in (out.err + out.out)
    assert "REVERSIBLE" not in out.out


# -- the README's table against the script that prints it ---------------------


def test_the_readme_table_is_what_the_sweep_prints():
    """The README's prose argues for an `order` column the sweep had stopped printing.

    Four columns were there on purpose - set equality and column position are different
    answers, and the paragraph above the table says so - and the script had been reduced
    to three. Nothing compared the two, so the README described a table that no longer
    existed and a reader running `scripts/sweep.py` got something else.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "scripts/sweep.py"],
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        env={**os.environ, "PYTHONPATH": "src"},
        timeout=300,
    )
    assert done.returncode == 0, (done.stdout + done.stderr)[-800:]
    printed = done.stdout.split("\nthe ones that pass")[0].rstrip()

    readme = (root / "README.md").read_text(encoding="utf-8")
    start = readme.index("```\nmigration ") + 4
    quoted = readme[start : readme.index("```", start)].rstrip()
    assert quoted == printed, (
        "the README's table is not what scripts/sweep.py prints.\n\nIt prints:\n"
        + printed
        + "\n\nThe README says:\n"
        + quoted
    )


def test_the_table_has_the_four_columns_the_prose_argues_for():
    """Named, so losing one fails here rather than in a paragraph nobody rereads."""
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    header = next(ln for ln in readme.splitlines() if ln.startswith("migration "))
    assert header.split()[1:] == ["schema", "order", "data", "verdict"], header
