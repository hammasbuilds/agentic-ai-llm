"""Apply a migration to a throwaway copy of the schema and observe what happened.

The claim a migration pair makes is that `down` undoes `up`. That claim is
almost never tested, and when it is tested it is tested against the *schema* -
which round-trips easily - rather than against the *data*, which frequently
does not.

So this module does both: it snapshots schema and rows before `up`, applies
`up`, applies `down`, and snapshots again. A migration that restores the schema
exactly and loses eleven rows is reported as lossy, not as reversible.

sqlite3 from the standard library is the shadow engine. It is not Postgres and
the README says so; what it does give is a real SQL engine that can be created,
destroyed and compared in milliseconds, with no server and no dependency.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field


class MigrationFailed(RuntimeError):
    """A statement did not execute. The SQL text and the engine error are attached."""

    def __init__(self, phase: str, statement: str, error: str):
        super().__init__(f"{phase} failed: {error}\n  in: {statement.strip()[:160]}")
        self.phase = phase
        self.statement = statement
        self.error = error


@dataclass(frozen=True)
class TableSnapshot:
    name: str
    columns: tuple[tuple[str, str, int], ...]  # (name, declared type, notnull)
    row_count: int
    checksum: str  # over the rows, order-independent

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c[0] for c in self.columns)


@dataclass(frozen=True)
class Snapshot:
    tables: dict[str, TableSnapshot]
    indexes: frozenset[str]

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(self.tables)

    @property
    def total_rows(self) -> int:
        return sum(t.row_count for t in self.tables.values())


def split_statements(sql: str) -> list[str]:
    """Split a script on semicolons that are not inside a string or comment.

    A naive `sql.split(";")` breaks on any default value containing a
    semicolon, and on `BEGIN ... END` trigger bodies. This is still not a SQL
    parser, and the README is explicit about that, but it survives the cases
    that actually appear in migration files.
    """
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0  # BEGIN ... END nesting
    i = 0
    text = _strip_comments(sql)

    while i < len(text):
        ch = text[i]
        if quote:
            buffer.append(ch)
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    buffer.append(text[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if ch in "'\"":
            quote = ch
            buffer.append(ch)
            i += 1
            continue

        word_match = re.match(r"\b(BEGIN|END)\b", text[i:], re.IGNORECASE)
        if word_match:
            keyword = word_match.group(1).upper()
            # A bare `BEGIN;` is a transaction, not a block.
            following = text[i + len(word_match.group(0)) :].lstrip()
            if keyword == "BEGIN" and not following.startswith(";"):
                depth += 1
            elif keyword == "END":
                depth = max(0, depth - 1)
            buffer.append(word_match.group(0))
            i += len(word_match.group(0))
            continue

        if ch == ";" and depth == 0:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            i += 1
            continue

        buffer.append(ch)
        i += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _strip_comments(sql: str) -> str:
    out: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def connect(schema_sql: str = "", seed_sql: str = "") -> sqlite3.Connection:
    """A fresh in-memory database with the starting schema and rows applied."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for phase, script in (("schema", schema_sql), ("seed", seed_sql)):
        for statement in split_statements(script):
            try:
                conn.execute(statement)
            except sqlite3.Error as exc:
                raise MigrationFailed(phase, statement, str(exc)) from exc
    conn.commit()
    return conn


def apply(conn: sqlite3.Connection, script: str, phase: str) -> list[str]:
    """Run every statement in a script, returning the statements executed."""
    executed: list[str] = []
    for statement in split_statements(script):
        try:
            conn.execute(statement)
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationFailed(phase, statement, str(exc)) from exc
        executed.append(statement)
    conn.commit()
    return executed


def _table_checksum(conn: sqlite3.Connection, table: str, columns: list[str]) -> str:
    """Order-independent hash of a table's contents.

    Rows are hashed individually and the hashes XOR-folded, so a migration that
    reorders rows - a rebuild, a re-insert - is not reported as data loss.
    """
    quoted = ", ".join(f'"{c}"' for c in columns)
    folded = 0
    for row in conn.execute(f'SELECT {quoted} FROM "{table}"'):
        encoded = "\x1f".join("\x00" if v is None else str(v) for v in row)
        digest = hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).digest()
        folded ^= int.from_bytes(digest, "big")
    return f"{folded:032x}"


def snapshot(conn: sqlite3.Connection) -> Snapshot:
    """Schema and contents, in a form two snapshots can be compared by."""
    tables: dict[str, TableSnapshot] = {}
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for name in names:
        info = list(conn.execute(f'PRAGMA table_info("{name}")'))
        columns = tuple((r[1], (r[2] or "").upper(), r[3]) for r in info)
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        checksum = _table_checksum(conn, name, [c[0] for c in columns])
        tables[name] = TableSnapshot(name, columns, count, checksum)

    indexes = frozenset(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    )
    return Snapshot(tables=tables, indexes=indexes)


@dataclass
class RoundTrip:
    """What `up` then `down` actually did."""

    before: Snapshot
    after_up: Snapshot
    after_down: Snapshot
    up_statements: list[str] = field(default_factory=list)
    down_statements: list[str] = field(default_factory=list)

    @property
    def missing_tables(self) -> list[str]:
        return sorted(self.before.table_names - self.after_down.table_names)

    @property
    def columns_lost(self) -> list[str]:
        """Columns present before and absent after the round trip."""
        out = []
        for name, original in self.before.tables.items():
            restored = self.after_down.tables.get(name)
            if restored is None:
                continue
            for column in set(original.column_names) - set(restored.column_names):
                out.append(f"{name}.{column}")
        return sorted(out)

    @property
    def extra_tables(self) -> list[str]:
        """Tables `down` created or failed to drop."""
        return sorted(self.after_down.table_names - self.before.table_names)

    @property
    def columns_added(self) -> list[str]:
        """Columns absent before and present after the round trip.

        The mirror of `columns_lost`, and it was missing. Every comparison here looked
        for things the round trip LOST, so a `down` that failed to drop the column its
        `up` added left the schema changed and `schema_equivalent` said "same tables,
        same columns" anyway - the docstring describing a symmetric comparison over an
        implementation that only ran one way.

        It is not cosmetic: an extra column means the next `up` fails with "column
        already exists", so a migration reported as fully reversible cannot in fact be
        re-applied.
        """
        out = []
        for name, restored in self.after_down.tables.items():
            original = self.before.tables.get(name)
            if original is None:
                continue
            for column in set(restored.column_names) - set(original.column_names):
                out.append(f"{name}.{column}")
        return sorted(out)

    @property
    def columns_reordered(self) -> list[str]:
        """Tables whose columns all came back, but in a different order.

        SQLite - and Postgres - append a re-added column at the end rather
        than restoring its original position. Everything still works until
        something does `SELECT *` and relies on position, or an `INSERT`
        omits the column list. The schemas are equal as sets and not as
        sequences, and that difference deserves its own line.
        """
        out = []
        for name, original in self.before.tables.items():
            restored = self.after_down.tables.get(name)
            if restored is None:
                continue
            if original.column_names == restored.column_names:
                continue
            if set(original.column_names) == set(restored.column_names):
                out.append(name)
        return sorted(out)

    @property
    def types_changed(self) -> list[str]:
        out = []
        for name, original in self.before.tables.items():
            restored = self.after_down.tables.get(name)
            if restored is None:
                continue
            before = {c[0]: (c[1], c[2]) for c in original.columns}
            after = {c[0]: (c[1], c[2]) for c in restored.columns}
            for column, spec in before.items():
                if column in after and after[column] != spec:
                    out.append(f"{name}.{column}")
        return sorted(out)

    @property
    def schema_equivalent(self) -> bool:
        """Same tables, same columns, same types - order not considered.

        Both directions. This checked `missing_tables`, `columns_lost` and
        `types_changed` only, so a `down` that failed to drop what its `up` added was
        "equivalent": the docstring said "same columns" and the code asked whether any
        had gone. `ALTER TABLE t ADD COLUMN c` with an empty `down` reported FULLY
        REVERSIBLE, on a schema that still has `c` and an `up` that can no longer run.
        """
        if self.missing_tables or self.extra_tables:
            return False
        if self.columns_lost or self.columns_added or self.types_changed:
            return False
        return self.before.indexes == self.after_down.indexes

    @property
    def schema_restored(self) -> bool:
        """Does `down` return the schema to exactly what it was, order included?"""
        return self.schema_equivalent and not self.columns_reordered

    @property
    def data_restored(self) -> bool:
        """Does `down` return the *rows* to exactly what they were?

        This is the question nobody asks. A down-migration that recreates a
        dropped column restores the schema perfectly and fills the column with
        NULL, because the values were deleted by `up` and nothing kept them.
        """
        if self.before.table_names != self.after_down.table_names:
            return False
        return all(
            self.before.tables[name].checksum == self.after_down.tables[name].checksum
            for name in self.before.tables
        )

    @property
    def rows_lost(self) -> int:
        return max(0, self.before.total_rows - self.after_down.total_rows)

    @property
    def verdict(self) -> str:
        if not self.schema_equivalent:
            return "schema not restored"
        if self.columns_reordered and not self.data_restored:
            return "columns reordered, data lost"
        if self.columns_reordered:
            return "columns reordered"
        if not self.data_restored:
            return "schema restored, data lost"
        return "fully reversible"

    def changed_tables(self) -> list[str]:
        out = []
        for name, original in self.before.tables.items():
            restored = self.after_down.tables.get(name)
            if restored is None or restored.checksum != original.checksum:
                out.append(name)
        return sorted(out)


def round_trip(schema_sql: str, seed_sql: str, up_sql: str, down_sql: str) -> RoundTrip:
    """Apply up then down on a throwaway database and compare all three states."""
    conn = connect(schema_sql, seed_sql)
    try:
        before = snapshot(conn)
        up_statements = apply(conn, up_sql, "up")
        after_up = snapshot(conn)
        down_statements = apply(conn, down_sql, "down")
        after_down = snapshot(conn)
    finally:
        conn.close()
    return RoundTrip(
        before=before,
        after_up=after_up,
        after_down=after_down,
        up_statements=up_statements,
        down_statements=down_statements,
    )
