"""The README's corpus table and its StockCode paragraph, against the real files.

The folder is named by `CSV_CORPUS` and defaults to a sibling checkout's
`machine-learning/data/raw`. These skip when it is absent, naming the folder, because
the files are a few hundred megabytes and are not committed here.

Two things in that README had no producer. The corpus table — files, columns,
warnings, the largest file and its duplicate rows — was quoted and nothing computed
it; its warning count was ten too high. And the paragraph about `StockCode` named the
four administrative codes and called them "the most common", which they are not: they
are 4.1% of the non-numeric values, and 95.5% are ordinary product codes ending in a
letter. A numeric cast on that column deletes 129 thousand real sales, not a handful
of postage lines.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

import pytest

from csvanalyst.cli import SWEEPABLE, _looks_delimited
from csvanalyst.profile import parse_number, profile_csv

README = Path(__file__).resolve().parents[1] / "README.md"
CORPUS = Path(
    os.environ.get("CSV_CORPUS")
    or Path(__file__).resolve().parents[4] / "machine-learning" / "data" / "raw"
)
RETAIL = CORPUS / "online-retail-ii.csv"

pytestmark = pytest.mark.skipif(not RETAIL.exists(), reason=f"no corpus at {CORPUS}")


def _stated(label: str) -> str:
    """One row of the README's corpus table."""
    found = re.search(
        rf"^\| {re.escape(label)} \| (.+?) \|$",
        README.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert found, f"the README no longer states {label!r}"
    return found.group(1)


def _number(label: str) -> int:
    return int(re.sub(r"[^\d]", "", _stated(label).split("(")[0]))


@pytest.fixture(scope="module")
def swept():
    profiled = [
        profile_csv(found)
        for found in sorted(CORPUS.iterdir())
        if found.is_file() and found.suffix.lower() in SWEEPABLE and _looks_delimited(found)
    ]
    assert profiled, "the corpus is present but nothing in it profiled"
    return profiled


def test_the_corpus_table_counts_what_is_in_the_folder(swept):
    files = [f for f in CORPUS.iterdir() if f.is_file()]
    assert _number("Files in the folder") == len(files)
    assert _number("Profiled") == len(swept)
    assert _number("Columns profiled") == sum(len(p.columns) for p in swept)
    assert _number("Warnings raised") == sum(len(p.all_warnings) for p in swept)


def test_the_largest_file_and_its_duplicates_are_the_measured_ones(swept):
    biggest = max(swept, key=lambda p: p.rows)
    assert Path(biggest.path).name == "online-retail-ii.csv"
    assert _number("Largest file") == biggest.rows
    assert _number("Exact duplicate rows in it") == biggest.duplicate_rows
    assert f"{biggest.duplicate_rows / biggest.rows * 100:.1f}%" in _stated(
        "Exact duplicate rows in it"
    )


def test_the_contaminated_columns_are_both_in_that_one_file(swept):
    found = [(Path(p.path).name, c.name) for p in swept for c in p.contaminated]
    assert _number("Contaminated numeric columns") == len(found)
    assert {name for name, _ in found} == {"online-retail-ii.csv"}


def test_an_arff_file_is_refused_rather_than_profiled_as_a_csv():
    """It gave one column named `@relation freMTPL2freq`, reported as contaminated.

    Two of those took the table's contaminated count from 2 to 4, both artefacts of
    this tool rather than anything in the data.
    """
    arff = sorted(CORPUS.glob("*.arff"))
    if not arff:
        pytest.skip("no .arff file in this corpus")
    for found in arff:
        assert not _looks_delimited(found), found.name


# -- the StockCode paragraph ----------------------------------------------


@pytest.fixture(scope="module")
def stock_codes():
    import csv as _csv

    profile = profile_csv(RETAIL)
    column = next(c for c in profile.columns if c.name == "StockCode")
    reader = _csv.reader(
        RETAIL.read_text(encoding="utf-8", errors="replace").splitlines(),
        delimiter=profile.delimiter,
    )
    next(reader, [])
    return Counter(
        row[column.index]
        for row in reader
        if column.index < len(row) and parse_number(row[column.index]) is None
    )


def test_most_non_numeric_stock_codes_are_products_not_postage(stock_codes):
    """The README named the 4% and called it the most common."""
    total = sum(stock_codes.values())
    suffixed = sum(
        n for code, n in stock_codes.items() if re.fullmatch(r"\d{4,6}[A-Za-z]{1,2}", code)
    )
    admin = sum(stock_codes.get(k, 0) for k in ("POST", "DOT", "M", "ADJUST", "BANK CHARGES"))

    assert total == 134_986
    assert suffixed / total > 0.95, f"{suffixed} of {total}"
    assert admin / total < 0.05
    assert suffixed > admin * 20, "the product codes outnumber the admin codes 23 to 1"

    readme = README.read_text(encoding="utf-8")
    assert f"{total:,}" in readme
    assert f"{suffixed / total * 100:.1f}%" in readme
    assert f"{suffixed:,} rows" in readme


def test_the_readme_quotes_the_three_most_common_in_order(stock_codes):
    top = [code for code, _ in stock_codes.most_common(3)]
    readme = README.read_text(encoding="utf-8")
    assert top == ["85123A", "85099B", "POST"], top
    # The two product codes are quoted as the top of the list; POST is quoted as one
    # of the administrative codes, with its count.
    for code in ("85123A", "85099B"):
        assert f"`{code}`" in readme
    assert f"`POST` {stock_codes['POST']:,}" in readme


# -- the headline block, and the command that now produces it -------------


def test_the_revenue_block_is_what_the_impact_command_prints():
    """It had no producer. The figures were right; one of them was wrong anyway.

    19,493 of 19,500 is 99.96%, printed as 100.0% and then leaned on in prose as
    "100% of the refunds - the only negative transactions in the file". Seven rows
    disagreed, and six of them are `Adjust bad debt` entries that reduce revenue
    through a negative price rather than a negative quantity - so counting what
    actually reduces the total gives 99.99% and a better finding.
    """
    import io
    import re
    from contextlib import redirect_stdout

    from csvanalyst.cli import main

    captured = io.StringIO()
    with redirect_stdout(captured):
        assert (
            main(
                [
                    "impact",
                    str(RETAIL),
                    "--coerce",
                    "Invoice",
                    "--quantity",
                    "Quantity",
                    "--price",
                    "Price",
                ]
            )
            == 0
        )
    printed = captured.getvalue()

    readme = README.read_text(encoding="utf-8")
    block = readme[readme.index("rows with parseable quantity/price") :]
    block = block[: block.index("```")].strip()
    assert block == printed.strip(), "the README block is not this command's output"

    # And the two percentages the prose quotes come from it.
    assert "99.96%" in printed and "99.99%" in printed
    assert "100.0%" not in printed, "the rounding that the prose leaned on"
    headline = readme[readme.index("## Results") : readme.index("```")]
    assert "99.99% of them reduce revenue" in headline
    assert "100.0% of them" not in headline

    numbers = dict(re.findall(r"^(\S[^:]*?)\s*:\s+([\d,.-]+)", printed, re.MULTILINE))
    assert numbers["rows with parseable quantity/price"] == "1,067,371"
    assert numbers["non-numeric Invoice rows"] == "19,500"


def test_the_two_rows_that_do_not_reduce_revenue_are_named():
    """A 99.99% claim has to say what the other 0.01% is."""
    import io
    from contextlib import redirect_stdout

    from csvanalyst.cli import main

    captured = io.StringIO()
    with redirect_stdout(captured):
        main(
            [
                "impact",
                str(RETAIL),
                "--coerce",
                "Invoice",
                "--quantity",
                "Quantity",
                "--price",
                "Price",
            ]
        )
    printed = captured.getvalue()

    assert "2 dropped row(s) whose line total is not negative" in printed
    assert "C496350" in printed and "A563185" in printed
    readme = README.read_text(encoding="utf-8")
    assert "C496350" in readme and "A563185" in readme


def test_impact_refuses_a_column_the_file_does_not_have():
    from csvanalyst.cli import main

    assert (
        main(
            [
                "impact",
                str(RETAIL),
                "--coerce",
                "Nope",
                "--quantity",
                "Quantity",
                "--price",
                "Price",
            ]
        )
        == 2
    )
