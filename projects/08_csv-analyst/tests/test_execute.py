"""Execution, validation and chart tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from csvanalyst.charts import bars, histogram, sparkline
from csvanalyst.execute import (
    Finding,
    ValidationFailed,
    column_summary,
    contamination_findings,
    load,
    run,
    validate,
)
from csvanalyst.narrate import narrate
from csvanalyst.profile import profile_csv


def write(tmp_path: Path, body: str, name: str = "d.csv") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


@pytest.fixture
def retail(tmp_path: Path) -> Path:
    """A miniature of the UCI retail shape: an invoice column with cancellations."""
    lines = ["Invoice,Quantity,Price"]
    for i in range(90):
        lines.append(f"{500000 + i},{i % 7 + 1},{(i % 5) + 1}.50")
    for i in range(6):
        lines.append(f"C{600000 + i},-{i + 1},2.50")
    return write(tmp_path, "\n".join(lines) + "\n")


# -- typing is taken from the profile ------------------------------------


def test_a_contaminated_column_is_loaded_as_text(retail: Path):
    """The enforcement point: the database must not be able to average it."""
    profile = profile_csv(retail)
    conn = load(retail, profile)
    types = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(data)")}
    assert types["Invoice"] == "TEXT"
    assert types["Quantity"] == "REAL"


def test_cancellation_rows_survive_the_load(retail: Path):
    profile = profile_csv(retail)
    conn = load(retail, profile)
    _, rows = run(conn, "SELECT COUNT(*) FROM data WHERE Invoice LIKE 'C%'")
    assert rows[0][0] == 6


def test_a_numeric_cast_would_have_dropped_them(retail: Path):
    """The counterfactual, measured rather than asserted."""
    profile = profile_csv(retail)
    conn = load(retail, profile)
    _, total = run(conn, "SELECT COUNT(*), SUM(Quantity) FROM data")
    _, numeric_only = run(
        conn,
        "SELECT COUNT(*), SUM(Quantity) FROM data WHERE CAST(Invoice AS REAL) > 0",
    )
    assert numeric_only[0][0] < total[0][0]
    assert numeric_only[0][1] > total[0][1]  # dropping returns inflates the total


# -- validation refuses bad results --------------------------------------


def _finding(**kw) -> Finding:
    base = dict(title="t", query="q", rows=[(1,)], columns=["c"], supporting=1, excluded=0)
    base.update(kw)
    return Finding(**base)


def test_an_empty_result_is_refused():
    with pytest.raises(ValidationFailed, match="no rows"):
        validate(_finding(rows=[]))


def test_a_result_with_no_supporting_rows_is_refused():
    with pytest.raises(ValidationFailed, match="no supporting rows"):
        validate(_finding(supporting=0))


def test_nan_is_refused():
    with pytest.raises(ValidationFailed, match="NaN"):
        validate(_finding(rows=[(float("nan"),)]))


def test_infinity_is_refused():
    with pytest.raises(ValidationFailed, match="infinite"):
        validate(_finding(rows=[(float("inf"),)]))


def test_unexplained_exclusions_are_refused():
    """A number computed over an unstated subset is exactly the failure mode."""
    with pytest.raises(ValidationFailed, match="no stated reason"):
        validate(_finding(excluded=5, exclusion_reason=""))


def test_heavy_exclusion_passes_but_gains_a_caveat():
    result = validate(_finding(supporting=10, excluded=40, exclusion_reason="null"))
    assert any("over half" in c for c in result.caveats)


# -- findings -------------------------------------------------------------


def test_identifier_and_contaminated_columns_get_no_distribution(tmp_path: Path):
    rows = "\n".join(f"{12000 + i},{i}" for i in range(60))
    path = write(tmp_path, f"CustomerID,qty\n{rows}\n")
    profile = profile_csv(path)
    conn = load(path, profile)
    titles = [f.title for f in column_summary(conn, profile)]
    assert not any("CustomerID" in t for t in titles)
    assert any("qty" in t for t in titles)


def test_contamination_finding_names_the_offending_values(retail: Path):
    profile = profile_csv(retail)
    conn = load(retail, profile)
    findings = contamination_findings(conn, profile)
    assert findings
    values = {row[0] for f in findings for row in f.rows}
    assert any(v.startswith("C") for v in values)


def test_narration_mentions_contamination_and_claims_no_model(retail: Path):
    profile = profile_csv(retail)
    conn = load(retail, profile)
    text = narrate(
        profile, column_summary(conn, profile) + contamination_findings(conn, profile)
    )
    assert "Invoice" in text
    assert "numeric cast" in text
    assert "No number here was written by a language model." in text


# -- charts ---------------------------------------------------------------


def test_histogram_is_valid_svg_and_keeps_outliers():
    svg = histogram([1.0] * 50 + [9999.0], "t")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "9999" in svg or "10.0k" in svg


def test_bars_escapes_labels():
    svg = bars([("<script>", 3.0)], "t")
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_empty_chart_inputs_do_not_crash():
    assert "no values" in histogram([], "t")
    assert "no values" in bars([], "t")
    assert sparkline([1.0]) == ""
