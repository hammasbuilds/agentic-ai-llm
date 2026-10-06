<h1 align="center">csv-analyst</h1>
<p align="center"><i>Profile a CSV, compute only what validates, and never narrate a number that was not computed</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-47%20%2B%209%20skipped-success" alt="tests">
  <img src="https://img.shields.io/badge/rows%20measured-1.07M-orange" alt="rows">
</p>

---

## Results

**In the UCI Online Retail II dataset, 19,500 rows have an invoice number that is not a
number. 99.99% of them reduce revenue - they are the cancellations and the bad-debt
adjustments. Loading that column as numeric drops exactly those rows, and overstates
total revenue by £1,674,282 - 8.68%.**

```
rows with parseable quantity/price:     1,067,371
non-numeric Invoice rows          :        19,500  (1.83%)
  of those, negative Quantity     :        19,493  (99.96%)
  of those, negative line total   :        19,498  (99.99%)

total, all rows                   :    19,287,250.57
total, numeric Invoice only       :    20,961,532.51
overstatement                     :     1,674,281.94   (+8.68%)

2 dropped row(s) whose line total is not negative, by Invoice: C496350, A563185
```

`csv-analyst impact <csv> --coerce Invoice --quantity Quantity --price Price` prints
that block. It used to have no producer at all: the figures were right - I re-derived
every one - but one of them was wrong, and a block nothing computes cannot be checked.
19,493 of 19,500 is **99.96%**, not the 100.0% it rounded to, and the prose leaned on the
rounding: "100% of the refunds - the only negative transactions in the file."

Counting what actually reduces revenue is both more accurate and a better finding.
**19,498 of the 19,500 have a negative line total — 99.99%** — because five of the seven
rows with a non-negative quantity are `Adjust bad debt` entries carrying a negative
*price* instead. Only two dropped rows do not reduce the figure: `C496350`, a £373.57
`Manual`, and `A563185`, a bad-debt adjustment that two identical negatives cancel out.

So the cast drops three kinds of row behind three invoice prefixes — `C` for
cancellations, `A` for adjustments, and the plain numeric ones it keeps — and the rows a
type coercion silently discards are **not a random sample**. Dropping 1.83% of rows moved
the headline figure by 8.68%, in the same direction every time.

So this tool refuses to coerce. A column that is 97.9% numeric is loaded as **text**, and
the values that would not parse get their own section of the report.

## Input / Output

**In:** a path to a CSV.

**Out:**

```
$ csv-analyst report online-retail-ii.csv

1,067,371 rows and 8 columns (5 numeric, 2 categorical, 1 date), delimiter ',', read as utf-8.

## Integrity

- 34,335 rows are exact duplicates of an earlier row (3.2%). Any count, sum or mean
  over this file double-counts them unless they are removed first.

## Columns a numeric cast would thin out

- `Invoice` is 98.2% numeric. The remaining 19,500 values ('C489449', 'C489459',
  'C489476') will not parse. Loading this column as a number drops those rows from
  every aggregate computed over it, and nothing in the output will say so. They are
  kept as text here.
- `StockCode` is 87.4% numeric. The remaining 134,986 values ('79323P', '79323W',
  '48173C') will not parse. ...

## Column warnings

- `Invoice`: 19500 of 1067371 values are not numbers ('C489449', 'C489459',
  'C489476') - any mean here silently excludes them
- `StockCode`: looks like an identifier rather than a measurement - its mean
  (28,350.2) is not a meaningful quantity
- `Quantity`: 360 value(s) beyond 8 standard deviations (e.g. 80995)
- `Price`: 250 value(s) beyond 8 standard deviations (e.g. -53594.4)
- `CustomerID`: looks like an identifier rather than a measurement - its mean
  (15,324.6) is not a meaningful quantity

## Computed

- Quantity: distribution: computed from 1,067,371 rows.
- Price: distribution: computed from 1,067,371 rows.
- Invoice: the values a numeric cast would delete: computed from 684 rows.
    Caveat: 19,500 values in this column are not numbers; loading it as numeric
    drops those rows from every aggregate
- StockCode: the values a numeric cast would delete: computed from 5,920 rows.
    Caveat: 134,986 values in this column are not numbers; loading it as numeric
    drops those rows from every aggregate

---
Every figure above was computed by a query that ran and passed validation.
No number here was written by a language model.
```

That block used to quote **120,000 rows and 1,292 duplicates (1.1%)** — a `--limit`
run, printed as though it were the file. The corpus table further down said 1,067,371
rows and 34,335 duplicates (3.2%) for the same file, so the README disagreed with
itself by a factor of nine on the number its headline finding rests on. Both are
regenerated from full runs now.

Also:

```
$ csv-analyst coercion <csv>           # what a silent numeric cast costs, per column
$ csv-analyst impact <csv> --coerce Invoice --quantity Quantity --price Price
                                       # what that cast does to a total - the block above
$ csv-analyst charts <csv> --out dir   # one SVG per column, no plotting library
$ csv-analyst sweep <folder>           # every delimited file in it - the table below
$ uv run --extra ui marimo edit ui/notebook.py
```

## Measured across 13 real datasets

The files in `machine-learning/data/raw`, each with a SHA-256 recorded at download.
`csv-analyst sweep <folder>` prints this table; it used to be quoted with nothing here
computing it, and the warning count was ten too high.

| | |
|---|---|
| Files in the folder | 18 |
| Profiled | 13 |
| Columns profiled | 816 |
| Warnings raised | 134 |
| Largest file | 1,067,371 rows (`online-retail-ii.csv`) |
| Exact duplicate rows in it | 34,335 (3.2%) |
| Contaminated numeric columns | 2 (both in that file) |

The five not profiled are named rather than dropped: three zips, and two `.arff` files,
which are not delimited text with a header row. Profiling one as a CSV gave a single
column literally named `@relation freMTPL2freq` and then reported it as a **contaminated
numeric column** — which took this table''s last row from 2 to 4, both of the extras
artefacts of the tool rather than anything in the data. A file whose first line starts
with `@`, `%`, `<` or `{` is refused as not delimited.

`StockCode`'s 134,986 non-numeric values are 1,715 distinct codes, and counting them
changes what the finding is. **95.5% of them — 128,892 rows — are ordinary product codes
with a letter suffix**: `85123A`, `85099B`, `82494L`, the top three. The administrative
codes are 4.1%: `POST` 2,122, `DOT` 1,446, `M` 1,421, `BANK CHARGES` 102, `ADJUST` 67.

This paragraph used to name only those administrative codes and conclude that a numeric
cast "deletes every shipping and adjustment line from the file". It does, and that is the
small half of it: the cast deletes 129 thousand sales of real products whose code happens
to end in a letter, which is twenty-three times as many rows and is not a category of
exception at all.

## Three enforcement points, not three warnings

A warning in a log is a paragraph nobody reads. Each rule here changes what the code can
physically do:

1. **A contaminated column is created as `TEXT` in SQLite.** The database cannot average
   it, so no later query can accidentally do so.
2. **Identifier columns are excluded from `is_quantity`.** The first version printed
   `mean CustomerID = 15,316.2` directly underneath a warning saying that number was
   meaningless. Now nothing downstream is offered the column.
3. **A finding must pass validation before the narrator can use it.** Empty results, NaN,
   infinity, and any exclusion without a stated reason all raise rather than print. The
   narrator has no free-text step and no model, so there is nothing that can invent a
   figure.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`.

DuckDB and pandas were the planned stack. For aggregates over a single table, `sqlite3`
from the standard library is enough, and it has the property that matters here: the
column types are declared by the loader, so a contaminated column *cannot* be averaged.
`matplotlib` would be forty megabytes to draw rectangles, so the charts are SVG written
by hand. `marimo` is an optional extra used only by the notebook view.

## Scope

- **Does not fix your data.** It refuses to guess what `C489449` means. It reports that
  19,500 rows carry values like it and that they will vanish under a cast.
- **Does not use a model.** The narration is templates filled from validated findings.
  A model would write better sentences and could write them about numbers it never saw.
- **Reads the whole file into memory.** Fine to a few million rows on a normal machine;
  use `--limit` beyond that.
- **One table at a time.** No joins, no multi-file relationships.
- **Heuristics, not certainties.** "Looks like an identifier" is a guess from the name
  and the value distribution, and it is reported as a warning rather than acted on
  silently - which is the entire argument of the project applied to itself.

## Run it

```bash
uv run pytest -q                                  # 56 passed, 9 skipped
uv run csv-analyst report <csv> --limit 100000
uv run csv-analyst coercion <csv>
uv run --extra ui marimo edit ui/notebook.py
```

The nine skips are the tests that measure over the real corpus, and they are the ones
behind every figure in Results. `CSV_CORPUS` names the folder holding
`online-retail-ii.csv`; point it there and all 56 run. It defaults to a path beside this
checkout, which is how those nine came to run during a sweep whose recorded counts are
published as a fresh clone's - the variable was missing from the list that sweep
withholds, so 56 passed / 0 skipped was recorded where a reader gets 47 / 9.

## Layout

```
src/csvanalyst/
    profile.py   type inference with evidence, contamination and identifier detection
    execute.py   SQLite load with declared types, queries, and validation
    charts.py    SVG histograms and bars, no plotting library
    narrate.py   templates filled only from validated findings
    cli.py       argparse
ui/notebook.py   marimo notebook (optional extra)
tests/
    test_profile.py  32 tests (parametrised)
    test_execute.py  15 tests
```
