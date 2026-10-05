"""Marimo notebook view for csv-analyst.

    uv run --extra ui marimo edit ui/notebook.py

Marimo rather than Jupyter because cells re-run on dependency change, so
picking a different file updates every panel below it without anyone
remembering to run the cells in order - which is the usual way a notebook ends
up showing a chart of one dataset beside a table of another.
"""

from __future__ import annotations

import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    import marimo as mo

    from csvanalyst.charts import bars, histogram
    from csvanalyst.execute import column_summary, contamination_findings, load
    from csvanalyst.profile import parse_number, profile_csv

    return (
        Path, bars, column_summary, contamination_findings, histogram,
        load, mo, parse_number, profile_csv,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # csv-analyst

        Profiles a CSV, then computes **only what validates**. A column that is
        mostly-but-not-entirely numeric is kept as text rather than coerced, so
        the rows a numeric cast would silently delete stay visible.
        """
    )
    return


@app.cell
def _(Path, mo):
    folder = mo.ui.text(
        value=str(Path.home() / "code" / "machine-learning" / "data" / "raw"),
        label="Folder",
        full_width=True,
    )
    folder
    return (folder,)


@app.cell
def _(Path, folder, mo):
    candidates = sorted(Path(folder.value).glob("*.csv")) if folder.value else []
    picker = mo.ui.dropdown(
        options={p.name: str(p) for p in candidates},
        value=candidates[0].name if candidates else None,
        label="CSV",
    )
    row_cap = mo.ui.slider(
        start=5_000, stop=500_000, step=5_000, value=100_000, label="Rows to read"
    )
    mo.hstack([picker, row_cap], justify="start", gap=1)
    return picker, row_cap


@app.cell
def _(mo, picker, profile_csv, row_cap):
    mo.stop(not picker.value, mo.md("*Pick a CSV above.*"))
    prof = profile_csv(picker.value, limit=row_cap.value)
    mo.md(
        f"**{prof.rows:,} rows x {len(prof.columns)} columns** &nbsp; "
        f"delimiter `{prof.delimiter}` &nbsp; encoding `{prof.encoding}` &nbsp; "
        f"duplicates **{prof.duplicate_rows:,}** &nbsp; ragged **{prof.ragged_rows:,}**"
    )
    return (prof,)


@app.cell
def _(mo, prof):
    contaminated = prof.contaminated
    mo.stop(
        not contaminated,
        mo.callout("No column is partially numeric. Nothing would be silently dropped.",
                   kind="success"),
    )
    rows = "\n".join(
        f"| `{c.name}` | {c.parse_rate:.1%} | {c.present - c.parsed:,} | "
        f"{', '.join(repr(v) for v in c.unparsed_examples[:3])} |"
        for c in contaminated
    )
    mo.callout(
        mo.md(
            "### Columns a numeric cast would thin out\n\n"
            "| Column | Numeric | Rows dropped | Examples |\n|---|---|---|---|\n"
            + rows
            + "\n\nThese are kept as text. Loading them as numbers removes those "
            "rows from every aggregate, with no message."
        ),
        kind="warn",
    )
    return


@app.cell
def _(mo, prof):
    warnings = prof.all_warnings
    mo.stop(not warnings, mo.md(""))
    mo.accordion(
        {
            f"Column warnings ({len(warnings)})": mo.md(
                "\n".join(f"- `{name}`: {text}" for name, text in warnings)
            )
        }
    )
    return


@app.cell
def _(column_summary, contamination_findings, load, mo, picker, prof, row_cap):
    conn = load(picker.value, prof, limit=row_cap.value)
    findings = column_summary(conn, prof) + contamination_findings(conn, prof)
    mo.md(
        "### Computed and validated\n\n"
        + "\n".join(
            f"- **{f.title}** - from {f.supporting:,} rows"
            + (f", excluding {f.excluded:,} ({f.exclusion_reason})" if f.excluded else "")
            for f in findings
        )
        + "\n\nEvery figure passed validation before being shown. Nothing here was "
        "written by a language model."
    )
    return (conn,)


@app.cell
def _(bars, histogram, mo, parse_number, picker, prof, row_cap):
    import csv as _csv

    text = open(picker.value, encoding="utf-8", errors="replace").read()
    reader = _csv.reader(text.splitlines(), delimiter=prof.delimiter)
    next(reader, None)
    sample = [r for _, r in zip(range(row_cap.value), reader, strict=False)]

    panels = []
    for col in prof.columns:
        values = [r[col.index] for r in sample if col.index < len(r)]
        if col.is_quantity:
            nums = [n for n in (parse_number(v) for v in values) if n is not None]
            panels.append(mo.Html(histogram(nums, f"{col.name} (n={len(nums):,})")))
        elif col.top_values:
            panels.append(
                mo.Html(bars([(v, float(n)) for v, n in col.top_values],
                             f"{col.name}: most common"))
            )
    mo.vstack(panels) if panels else mo.md("*No chartable columns.*")
    return


if __name__ == "__main__":
    app.run()
