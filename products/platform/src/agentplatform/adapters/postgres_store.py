"""Postgres, behind the Store port.

One table with a JSONB payload rather than twenty migrations, because the store
is the run ledger — the product's own schema lives alongside it and is not this
package's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DDL = """
CREATE TABLE IF NOT EXISTS agent_rows (
    tbl  text  NOT NULL,
    key  text  NOT NULL,
    row  jsonb NOT NULL,
    PRIMARY KEY (tbl, key)
)
"""


@dataclass
class PostgresStore:
    dsn: str = "postgresql://agent:agent@127.0.0.1:5432/agent"
    _conn: object = field(default=None, repr=False)

    def conn(self):
        if self._conn is None:
            import psycopg  # noqa: PLC0415 — optional extra

            self._conn = psycopg.connect(self.dsn, autocommit=True)
            self._conn.execute(DDL)
        return self._conn

    def put(self, table: str, key: str, row: dict) -> None:
        from psycopg.types.json import Jsonb  # noqa: PLC0415 — optional extra

        self.conn().execute(
            "INSERT INTO agent_rows (tbl, key, row) VALUES (%s, %s, %s) "
            "ON CONFLICT (tbl, key) DO UPDATE SET row = EXCLUDED.row",
            (table, key, Jsonb(row)),
        )

    def get(self, table: str, key: str) -> dict | None:
        found = (
            self.conn()
            .execute("SELECT row FROM agent_rows WHERE tbl = %s AND key = %s", (table, key))
            .fetchone()
        )
        return found[0] if found else None

    def rows(self, table: str) -> list[dict]:
        found = (
            self.conn()
            .execute("SELECT row FROM agent_rows WHERE tbl = %s ORDER BY key", (table,))
            .fetchall()
        )
        return [r[0] for r in found]

    def reachable(self) -> bool:
        try:
            self.conn().execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 — reachability is a boolean
            return False
