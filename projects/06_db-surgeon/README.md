<h1 align="center">db-surgeon</h1>
<p align="center"><i>Prove a migration's rollback on a throwaway copy before trusting it</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-44-success" alt="tests">
  <img src="https://img.shields.io/badge/corpus-12%20migrations-orange" alt="corpus">
</p>

---

## Results

**Of 12 migration pairs written the way people write them, 10 ran. Three of those a schema
check passes, and all three lose data.** A review that compares schemas - which is what
schema-diff tooling compares - passes all three.

The table used to print one `schema` column while the count used a different definition of
it. The column showed set equality *and* original column order; the count ignored order,
which is what a diff tool does. So `drop an unused column` read `NO` in the table and was
one of the three in the total, and the same output disagreed with itself - by the table's
own column the answer was 2. `order` is its own column now, and the summary says how many
of the three moved a column as well.

```
migration                             schema  order   data  verdict
----------------------------------------------------------------------------------
add a nullable column                     ok     ok     ok  fully reversible
drop an unused column                     ok  MOVED   LOST  columns reordered, data lost
rename a column                           ok     ok     ok  fully reversible
add an index                              ok     ok     ok  fully reversible
drop an index                             ok     ok     ok  fully reversible
backfill a default                         -      -      -  did not run
normalise a value in place                ok     ok     ok  fully reversible
drop a lookup table                       NO     ok   LOST  schema not restored
widen a column type                       ok     ok     ok  fully reversible
clear a column before removing it         ok     ok   LOST  schema restored, data lost
delete soft-deleted rows                  ok     ok   LOST  schema restored, data lost
add a NOT NULL column with no default       -      -      -  did not run
----------------------------------------------------------------------------------
12 migrations, 10 ran, 6 fully reversible, 3 match on schema and lose data
    of those 3, 1 also moved a column, which a schema-diff tool does not compare and this table now shows
```

The canonical case is `drop a column`:

```sql
-- up
ALTER TABLE users DROP COLUMN nickname;
-- down
ALTER TABLE users ADD COLUMN nickname TEXT;
```

The down-migration recreates the column. The column lists compare equal. Every value is
NULL forever, because `up` deleted them and nothing in the pair kept a copy. This is not
an exotic mistake - it is the obvious inverse, and it is wrong.

## A second thing schema comparison misses

`drop an unused column` also comes back **in a different position**. SQLite appends a
re-added column at the end rather than restoring its original slot, and so does Postgres.
The columns match as a *set* and not as a *sequence*, so anything relying on `SELECT *`
ordering, or an `INSERT` without a column list, silently changes meaning.

Reported as its own outcome rather than folded into "schema restored".

## Input / Output

```
$ db-surgeon check --schema schema.sql --seed seed.sql --up up.sql --down down.sql

==============================================================================
  drop_nickname  -  SCHEMA RESTORED, DATA LOST
==============================================================================

  ROUND TRIP  (up, then down, on a throwaway copy)
    schema restored : yes
    data restored   : NO
    tables altered  : users
    rows lost       : 0

    The schema comparison passes and the data comparison does not.
    A review that checks only the schema would call this reversible.

  UP  {'lossy': 1}
    [LOSSY] drop_column              users
             the column's values are deleted; recreating the column restores NULLs
==============================================================================
```

Also:

```
$ db-surgeon classify migration.sql   # static reading; runs nothing
$ db-surgeon corpus                   # the table above
$ db-surgeon check ... --strict       # exit 1 unless fully reversible, for CI
$ python ui/server.py                 # API for the SolidJS UI on :8095
```

## Two sources of truth, and they disagree

Static classification reads the SQL and predicts. The shadow round-trip executes it and
observes. They are kept separate and **the disagreements are printed**, because a rule
that mispredicts is a defect in this tool rather than something to hide behind a
confident verdict. On the corpus, three of ten:

| Migration | Disagreement |
|---|---|
| normalise a value in place | predicted loss; the round trip restored everything - `UPDATE ... SET email = LOWER(email)` on already-lowercase data changes nothing |
| widen a column type | predicted loss; the round trip restored everything - the values are copied into the new column and back |
| delete soft-deleted rows | **no rule predicted loss; the round trip lost a row** - `DELETE ... WHERE status = 'disabled'` has a `WHERE` clause, so the unqualified-delete rule never fires |

The last one is the honest admission: pattern matching over SQL text cannot know whether
a `WHERE` clause matches anything. That is precisely why the round-trip exists, and why
`check` is documented as the authority over `classify`.

## Two migrations the database refused outright

`backfill a default` and `add a NOT NULL column with no default` never ran. The second is
the well-known one - `ALTER TABLE ... ADD COLUMN c TEXT NOT NULL` fails on any table that
already has rows - and it is worth noting that **this tool did not need a rule to catch
it**. The engine rejected it. A shadow database catches a whole class of problems without
anyone writing a check for them.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`.

`sqlglot` and `Alembic` were the planned stack. Neither is needed: the shadow engine is
`sqlite3` from the standard library, and executing the migration is a better test than
parsing it. The UI's API is `http.server`; only the SolidJS front end needs npm.

## Scope

- **It is SQLite, not your database.** Postgres-specific DDL, `CONCURRENTLY`, partial
  indexes and vendor types will not run here. What transfers is the method and the
  reversibility verdict for standard SQL; what does not is anything vendor-specific. This
  is the single biggest limitation and it is not a small one.
- **`classify` is pattern matching, not a parser.** It has a measured false-positive and
  false-negative rate on its own corpus, printed above.
- **It cannot know whether losing data is wrong.** `delete soft-deleted rows` may be
  exactly what was intended. The tool reports that a row went and did not come back; the
  decision is yours.
- **No locking or performance simulation.** `blocking` is a static label about statements
  known to take locks, not a measurement against a live table.
- **The API server executes SQL from a request body** and is bound to localhost for that
  reason. Do not expose it.

## Run it

```bash
uv run pytest -q                  # 44 tests
uv run db-surgeon corpus
uv run python scripts/sweep.py
uv run python ui/server.py        # then: cd ui && npm install && npm run dev
```

## Layout

```
src/dbsurgeon/
    shadow.py      statement splitting, snapshots, the up/down round trip
    operations.py  static classification: reversible, lossy, blocking
    plan.py        combines the two and reports where they disagree
    cli.py         argparse
migrations/corpus.py  12 migration pairs that look correct in review
scripts/sweep.py      produces the table above
ui/                   SolidJS + Vite front end, http.server API
tests/
    test_shadow.py      21 tests
    test_operations.py  21 tests (parametrised)
```
