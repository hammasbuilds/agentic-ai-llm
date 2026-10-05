"""Load a CSV into SQLite, run the analysis, and validate before anyone narrates it.

The rule this module enforces: **no sentence is written about a number that was
not computed and checked.** Every finding carries the query that produced it,
the row count behind it, and the rows that were excluded to get it.

SQLite is used rather than DuckDB or pandas because it is in the standard
library and the queries here are aggregates over one table. Column types are
declared from the profile, not sniffed by the database, so a column the
profiler called contaminated is loaded as TEXT and cannot be silently averaged.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .profile import ColumnProfile, TableProfile, parse_number

TABLE = "data"


class ValidationFailed(RuntimeError):
    """A computed result did not survive its own checks, so it is not reported."""


@dataclass
class Finding:
    """One computed, validated result. The unit the narrator is allowed to use."""

    title: str
    query: str
    rows: list[tuple]
    columns: list[str]
    supporting: int  # rows the result was computed from
    excluded: int  # rows excluded, and why, stated below
    exclusion_reason: str = ""
    caveats: list[str] = field(default_factory=list)

    @property
    def scalar(self):
        return self.rows[0][0] if self.rows and self.rows[0] else None


def _sqlite_type(column: ColumnProfile) -> str:
    """A contaminated column is TEXT, so the database cannot average it.

    This is the enforcement point. The profiler can warn all it likes; if the
    column arrives as REAL then some later query will take its mean and the
    warning will be a paragraph nobody read.
    """
    if column.is_contaminated:
        return "TEXT"
    if column.kind == "numeric":
        return "REAL"
    return "TEXT"


def _safe(name: str) -> str:
    """Quote an identifier. Column names in real CSVs contain spaces and quotes."""
    return '"' + name.replace('"', '""') + '"'


def load(path: Path, profile: TableProfile, limit: int | None = None) -> sqlite3.Connection:
    """Load the CSV into an in-memory table with types taken from the profile."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = None

    cols = ", ".join(f"{_safe(c.name)} {_sqlite_type(c)}" for c in profile.columns)
    conn.execute(f"CREATE TABLE {TABLE} ({cols})")

    placeholders = ", ".join("?" for _ in profile.columns)
    insert = f"INSERT INTO {TABLE} VALUES ({placeholders})"

    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = Path(path).read_text(encoding="latin-1")

    reader = csv.reader(text.splitlines(), delimiter=profile.delimiter)
    next(reader, None)

    batch: list[tuple] = []
    width = len(profile.columns)
    for i, row in enumerate(reader):
        if limit is not None and i >= limit:
            break
        padded = list(row[:width]) + [""] * max(0, width - len(row))
        values = []
        for col, raw in zip(profile.columns, padded, strict=False):
            if _sqlite_type(col) == "REAL":
                values.append(parse_number(raw))
            else:
                values.append(raw)
        batch.append(tuple(values))
        if len(batch) >= 5000:
            conn.executemany(insert, batch)
            batch.clear()
    if batch:
        conn.executemany(insert, batch)
    conn.commit()
    return conn


def run(conn: sqlite3.Connection, query: str) -> tuple[list[str], list[tuple]]:
    cur = conn.execute(query)
    names = [d[0] for d in cur.description] if cur.description else []
    return names, cur.fetchall()


def validate(finding: Finding) -> Finding:
    """Refuse a result that cannot be described honestly.

    Checks are deliberately blunt. The purpose is not to judge whether the
    analysis is interesting, only to stop a number reaching prose when the
    number is empty, infinite, or computed from nothing.
    """
    if not finding.rows:
        raise ValidationFailed(f"{finding.title}: query returned no rows")
    if finding.supporting <= 0:
        raise ValidationFailed(f"{finding.title}: no supporting rows")

    for row in finding.rows[:50]:
        for value in row:
            if isinstance(value, float) and value != value:  # NaN
                raise ValidationFailed(f"{finding.title}: result contains NaN")
            if isinstance(value, float) and value in (float("inf"), float("-inf")):
                raise ValidationFailed(f"{finding.title}: result is infinite")

    if finding.excluded > 0 and not finding.exclusion_reason:
        raise ValidationFailed(
            f"{finding.title}: {finding.excluded} rows excluded with no stated reason"
        )
    if finding.supporting and finding.excluded / (finding.supporting + finding.excluded) > 0.5:
        finding.caveats.append(
            f"over half the rows ({finding.excluded:,}) were excluded - "
            f"treat this figure as describing a subset"
        )
    return finding


def column_summary(conn: sqlite3.Connection, profile: TableProfile) -> list[Finding]:
    """One validated finding per usable numeric column."""
    out: list[Finding] = []
    total = profile.rows
    for column in profile.columns:
        if not column.is_quantity:
            continue  # identifiers and contaminated columns have no meaningful mean
        name = _safe(column.name)
        query = (
            f"SELECT COUNT({name}), AVG({name}), MIN({name}), MAX({name}) "
            f"FROM {TABLE} WHERE {name} IS NOT NULL"
        )
        names, rows = run(conn, query)
        count = rows[0][0] if rows else 0
        finding = Finding(
            title=f"{column.name}: distribution",
            query=query,
            rows=rows,
            columns=names,
            supporting=count,
            excluded=total - count,
            exclusion_reason="null or unparseable" if total - count else "",
        )
        try:
            out.append(validate(finding))
        except ValidationFailed:
            continue
    return out


def contamination_findings(conn: sqlite3.Connection, profile: TableProfile) -> list[Finding]:
    """For each contaminated column, what the non-numeric values actually are.

    This is the point of the whole tool. A loader that coerced the column would
    have deleted these rows without a line of output; here they get their own
    section, because in every case examined so far they were a category rather
    than noise.
    """
    out: list[Finding] = []
    for column in profile.contaminated:
        name = _safe(column.name)
        query = (
            f"SELECT {name} AS value, COUNT(*) AS n FROM {TABLE} "
            f"WHERE {name} IS NOT NULL AND {name} != '' "
            f"  AND CAST({name} AS REAL) = 0.0 AND TRIM({name}) NOT IN ('0','0.0') "
            f"GROUP BY {name} ORDER BY n DESC LIMIT 15"
        )
        names, rows = run(conn, query)
        if not rows:
            continue
        affected = sum(r[1] for r in rows)
        finding = Finding(
            title=f"{column.name}: the values a numeric cast would delete",
            query=query,
            rows=rows,
            columns=names,
            supporting=affected,
            excluded=0,
            caveats=[
                f"{column.total - column.parsed:,} values in this column are not numbers; "
                f"loading it as numeric drops those rows from every aggregate"
            ],
        )
        try:
            out.append(validate(finding))
        except ValidationFailed:
            continue
    return out
