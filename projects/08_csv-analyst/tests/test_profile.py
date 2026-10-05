"""Profiler tests.

Fixtures are written as real CSV files, because the behaviour under test
includes delimiter sniffing, encoding fallback and ragged rows - none of which
survive being handed a clean list of lists.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from csvanalyst.profile import (
    _name_tokens,
    detect_date_format,
    honest_mean,
    naive_mean,
    parse_number,
    profile_csv,
)


def write(tmp_path: Path, name: str, body: str, encoding: str = "utf-8") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip(), encoding=encoding)
    return p


def column(profile, name: str):
    return next(c for c in profile.columns if c.name == name)


# -- number parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42.0),
        ("-3.5", -3.5),
        ("1,234", 1234.0),
        (" 7 ", 7.0),
        ("1e3", 1000.0),
        ("N/A", None),
        ("", None),
        ("12abc", None),
        ("C489449", None),
        ("--", None),
    ],
)
def test_number_parsing(raw: str, expected):
    assert parse_number(raw) == expected


# -- the contamination case ----------------------------------------------


def test_a_mostly_numeric_column_is_flagged_not_coerced(tmp_path: Path):
    """The failure the whole project is built on.

    99 numbers and one 'C1' is not a numeric column, and coercing it drops a
    row from every aggregate without saying so.
    """
    rows = "\n".join(str(i) for i in range(99))
    csv_path = write(tmp_path, "d.csv", f"invoice\n{rows}\nC1\n")
    profile = profile_csv(csv_path)
    invoice = column(profile, "invoice")
    assert invoice.kind == "numeric"
    assert invoice.is_contaminated
    assert not invoice.is_quantity
    assert "C1" in invoice.unparsed_examples
    assert any("silently excludes" in w for w in invoice.warnings)


def test_a_fully_numeric_column_is_not_flagged(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "n\n1\n2\n3\n4\n")
    col = column(profile_csv(csv_path), "n")
    assert col.is_quantity
    assert not col.is_contaminated


def test_a_mostly_text_column_is_not_called_numeric(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "c\nred\nblue\ngreen\n1\n")
    assert column(profile_csv(csv_path), "c").kind in ("categorical", "text")


def test_naive_and_honest_mean_agree_on_the_value_but_not_the_story():
    values = ["10", "20", "30", "N/A", "C1"]
    assert naive_mean(values) == 20.0
    mean, used, dropped = honest_mean(values)
    assert (mean, used, dropped) == (20.0, 3, 1)  # 'N/A' is null, 'C1' is dropped


# -- identifiers ----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CustomerID", ["customer", "id"]),
        ("customer_id", ["customer", "id"]),
        ("OrderNo", ["order", "no"]),
        ("price", ["price"]),
    ],
)
def test_camel_case_names_tokenise(name: str, expected: list[str]):
    """A regex needing a non-letter before 'id' missed CustomerID entirely."""
    assert _name_tokens(name) == expected


def test_an_id_column_is_not_offered_as_a_quantity(tmp_path: Path):
    rows = "\n".join(str(12000 + i) for i in range(60))
    csv_path = write(tmp_path, "d.csv", f"CustomerID\n{rows}\n")
    col = column(profile_csv(csv_path), "CustomerID")
    assert col.is_identifier
    assert not col.is_quantity
    assert any("identifier" in w for w in col.warnings)


def test_a_genuine_measurement_is_not_called_an_identifier(tmp_path: Path):
    rows = "\n".join(f"{v}" for v in [1.5, 2.5, 1.5, 3.0, 2.5, 1.5, 3.0, 2.5])
    csv_path = write(tmp_path, "d.csv", f"price\n{rows}\n")
    col = column(profile_csv(csv_path), "price")
    assert not col.is_identifier
    assert col.is_quantity


# -- sentinels ------------------------------------------------------------


def test_an_isolated_negative_sentinel_is_flagged(tmp_path: Path):
    rows = "\n".join(["-999"] * 5 + [str(i) for i in range(20, 60)])
    csv_path = write(tmp_path, "d.csv", f"temp\n{rows}\n")
    col = column(profile_csv(csv_path), "temp")
    assert any("sentinel" in w for w in col.warnings)


def test_minus_one_among_other_negatives_is_left_alone(tmp_path: Path):
    """In a quantity column, -1 means one item returned, not 'missing'.

    Flagging it was a false positive on the UCI retail data, where the column
    is full of negative quantities.
    """
    rows = "\n".join(["-1"] * 5 + ["-2", "-3", "-7", "-12"] + [str(i) for i in range(30)])
    csv_path = write(tmp_path, "d.csv", f"qty\n{rows}\n")
    col = column(profile_csv(csv_path), "qty")
    assert not any("sentinel" in w for w in col.warnings)


def test_a_constant_column_is_flagged(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "c\nx\nx\nx\nx\n")
    assert any("constant" in w for w in column(profile_csv(csv_path), "c").warnings)


# -- structure ------------------------------------------------------------


def test_duplicate_rows_are_counted(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "a,b\n1,2\n1,2\n3,4\n1,2\n")
    assert profile_csv(csv_path).duplicate_rows == 2


def test_ragged_rows_are_counted_not_fatal(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "a,b,c\n1,2,3\n4,5\n6,7,8,9\n")
    profile = profile_csv(csv_path)
    assert profile.ragged_rows == 2
    assert profile.rows == 3


def test_semicolon_delimiter_is_detected(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "a;b\n1;2\n3;4\n5;6\n")
    profile = profile_csv(csv_path)
    assert profile.delimiter == ";"
    assert [c.name for c in profile.columns] == ["a", "b"]


def test_non_utf8_file_is_read_not_refused(tmp_path: Path):
    p = tmp_path / "d.csv"
    p.write_bytes("name\ncaf\xe9\nrose\n".encode("latin-1"))
    profile = profile_csv(p)
    assert profile.encoding == "latin-1"
    assert profile.rows == 2


def test_empty_file_does_not_crash(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "")
    profile = profile_csv(csv_path)
    assert profile.rows == 0
    assert profile.columns == []


def test_limit_caps_rows_read(tmp_path: Path):
    rows = "\n".join(str(i) for i in range(100))
    csv_path = write(tmp_path, "d.csv", f"n\n{rows}\n")
    assert profile_csv(csv_path, limit=10).rows == 10


# -- dates ----------------------------------------------------------------


def test_one_format_is_detected_from_a_sample():
    """Trying eleven formats per value dominated the runtime on a 1M-row file."""
    assert detect_date_format(["2024-01-05", "2024-02-06", "2024-03-07"]) == "%Y-%m-%d"


def test_mixed_junk_yields_no_date_format():
    assert detect_date_format(["red", "blue", "green"]) is None


def test_a_date_column_is_classified_as_date(tmp_path: Path):
    csv_path = write(tmp_path, "d.csv", "when\n2024-01-05\n2024-02-06\n2024-03-07\n")
    assert column(profile_csv(csv_path), "when").kind == "date"
