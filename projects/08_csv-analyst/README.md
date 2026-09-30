<h1 align="center">csv-analyst</h1>
<p align="center"><i>Profile a CSV, compute only what validates, and never narrate a number that was not computed</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-47-success" alt="tests">
  <img src="https://img.shields.io/badge/rows%20measured-1.07M-orange" alt="rows">
</p>

---

## Results

**In the UCI Online Retail II dataset, 19,500 rows have an invoice number that is not a
number. 100.0% of them have a negative quantity: they are the cancellations. Loading that
column as numeric drops exactly those rows, and overstates total revenue by £1,674,282 -
8.68%.**

```
rows with parseable quantity/price : 1,067,371
non-numeric Invoice rows           :    19,500  (1.83%)
  of those, negative Quantity      :    19,493  (100.0%)

revenue, all rows                  : 19,287,250.57
revenue, numeric Invoice only      : 20,961,532.51
overstatement                      :  1,674,281.94   (+8.68%)
```

The rows a type coercion silently discards are **not a random sample**. Here they were
100% of the refunds - the only negative transactions in the file. Dropping 1.83% of rows
moved the headline figure by 8.68% and in the same direction every time.

So this tool refuses to coerce. A column that is 97.9% numeric is loaded as **text**, and
the values that would not parse get their own section of the report.

## Input / Output

**In:** a path to a CSV.

**Out:**

```
$ csv-analyst report online-retail-ii.csv

120,000 rows and 8 columns (5 numeric, 2 categorical, 1 date), delimiter ',', utf-8.

## Integrity
- 1,292 rows are exact duplicates of an earlier row (1.1%). Any count, sum or mean
  over this file double-counts them unless they are removed first.

## Columns a numeric cast would thin out
- `Invoice` is 97.9% numeric. The remaining 2,534 values ('C489449', 'C489459',
  'C489476') will not parse. Loading this column as a number drops those rows from
  every aggregate computed over it, and nothing in the output will say so.
- `StockCode` is 79.2% numeric. The remaining 24,925 values ('79323P', '79323W',
  '48173C') will not parse. ...

## Column warnings
- `CustomerID`: looks like an identifier rather than a measurement - its mean
  (15,316.2) is not a meaningful quantity
- `Price`: 81 value(s) beyond 8 standard deviations (e.g. 8985.6)

---
Every figure above was computed by a query that ran and passed validation.
No number here was written by a language model.
```

Also:

```
$ csv-analyst coercion <csv>          # what a silent numeric cast costs, per column
$ csv-analyst charts <csv> --out dir  # one SVG per column, no plotting library
$ uv run --extra ui marimo edit ui/notebook.py
```

## Measured across 13 real datasets

The files in `machine-learning/data/raw`, each with a SHA-256 recorded at download.

| | |
|---|---|
| Files | 13 |
| Columns profiled | 816 |
| Warnings raised | 146 |
| Largest file | 1,067,371 rows |
| Exact duplicate rows in it | 34,335 (3.2%) |
| Contaminated numeric columns | 2 |

`StockCode`'s 134,986 non-numeric values are not product codes either. The most common
are `POST`, `DOT`, `M` and `ADJUST` - postage, manual entries and adjustments. A numeric
cast deletes every shipping and adjustment line from the file.

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
uv run pytest -q                                  # 47 tests
uv run csv-analyst report <csv> --limit 100000
uv run csv-analyst coercion <csv>
uv run --extra ui marimo edit ui/notebook.py
```

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
