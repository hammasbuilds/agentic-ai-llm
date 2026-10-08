"""Every figure in the twenty-product index also appears in the product it links to.

`products/README.md` said "No figure below was typed by hand; each is asserted by a test
that runs the code over the data." Nothing read that file except its test counts, and
only nine of the twenty products have a test that reads their own README either. A
reviewer checked the rows against the code and found two stale:

  * **bid-desk**: "4,036 RFC 2119 requirements, 17 RFCs ... precision 0.827" - which the
    product's own README names as the figures that were wrong. `rfc._documents()` globs
    `rfc*.txt`, the shared corpus grew to 24 documents, and it is 4,304 and 0.825 now.
    `products/08_bid-desk/tests/test_real_requirements.py` bans the stale wording - in
    the PRODUCT readme. The ban was installed one directory below the copy that had it.
  * **watchtower**: "wrong 15.4% of the time", which is 14.2% false positive plus 1.2%
    false negative. Arithmetically consistent, and in no file.

This does not make the index's figures true - it makes the index agree with the product,
which is the strongest claim a cross-reference can make and is what the sentence there
now says. A figure wrong in both places is still wrong in both places, and the product's
own tests are what check it against the data.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products"
INDEX = PRODUCTS / "README.md"

#: A row of the index table: `| [NN](NN_name) | [**name**](NN_name) | corpus | finding |`
_ROW = re.compile(r"^\|\s*\[(\d\d)\]\((\d\d_[a-z-]+)\)\s*\|(.+)\|\s*$", re.M)

#: Every number in a cell, with its thousands separators and its percent sign. `1.000`
#: and `0.825` and `4,304` and `14.2%` are all figures; `08` from the link is not,
#: because the link column is stripped before this runs.
_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")

#: Figures that are not measurements of the product and need no counterpart: the index
#: number itself, and the years and version numbers that appear in a corpus description.
_NOT_A_MEASUREMENT = {"2119", "2"}


def _rows() -> dict[str, str]:
    text = INDEX.read_text(encoding="utf-8")
    rows = {}
    for _number, slug, rest in _ROW.findall(text):
        # Drop the name column; what is left is the corpus and the finding.
        cells = [c.strip() for c in rest.split("|")]
        rows[slug] = " ".join(cells[1:])
    return rows


def _normalise(figure: str) -> set[str]:
    """The spellings a product README might use for the same number.

    `4,304` and `4304`; `0.825` and `.825`; `14.2%` and `14.2`. A figure counts as
    present if any of its spellings is in the product README, because the index's
    typography is its own.
    """
    bare = figure.rstrip("%")
    out = {figure, bare, bare.replace(",", "")}
    if bare.startswith("0."):
        out.add(bare[1:])
    if "." not in bare and "," not in bare and len(bare) > 3:
        out.add(f"{int(bare):,}")
    return out


def test_the_index_has_a_row_for_every_product():
    """Or the sweep below is checking a subset and reporting a pass."""
    rows = _rows()
    on_disk = sorted(
        d.name for d in PRODUCTS.iterdir() if d.is_dir() and re.fullmatch(r"\d\d_[a-z-]+", d.name)
    )
    assert sorted(rows) == on_disk, {
        "in the index and not on disk": sorted(set(rows) - set(on_disk)),
        "on disk and not in the index": sorted(set(on_disk) - set(rows)),
    }
    assert len(rows) == 20, len(rows)


@pytest.mark.parametrize("slug", sorted(_rows()))
def test_every_figure_in_a_row_appears_in_the_product_readme(slug: str):
    readme = (PRODUCTS / slug / "README.md").read_text(encoding="utf-8")
    row = _rows()[slug]
    missing = []
    for figure in _FIGURE.findall(row):
        if figure in _NOT_A_MEASUREMENT:
            continue
        if not any(spelling in readme for spelling in _normalise(figure)):
            missing.append(figure)
    assert missing == [], (
        f"products/README.md quotes {missing} for {slug} and "
        f"products/{slug}/README.md does not. One of the two was re-measured and the "
        "other was not; the product's README is the one with the test behind it."
    )


def test_the_sweep_would_notice_a_figure_that_is_not_there():
    """The sensitivity check. A sweep that reports no missing figures is worth nothing
    until a planted one is found - and these spellings are generous enough that it is
    worth asking whether anything could fail.
    """
    readme = (PRODUCTS / "11_watchtower" / "README.md").read_text(encoding="utf-8")
    # The figure the index used to carry, which is the sum of two real ones.
    assert not any(spelling in readme for spelling in _normalise("15.4%")), (
        "15.4% is in watchtower's README now, so the case this test was written for "
        "no longer demonstrates anything"
    )
    # And one that IS there, so the matcher is not simply always-false.
    assert any(spelling in readme for spelling in _normalise("14.2%"))


def test_the_index_no_longer_claims_each_figure_is_asserted_against_the_data():
    """It claimed that while twelve of its rows had nothing reading them, and two were
    stale. What it can honestly say is that the index and the product agree."""
    text = INDEX.read_text(encoding="utf-8")
    assert "asserted by a test that runs the code over the data" not in text
    assert "tests/test_product_index.py" in text, (
        "the index should name the check that backs its claim"
    )


def _reads_a_readme(path: Path) -> bool:
    """Whether a test file opens a README, as opposed to mentioning one in prose.

    A string constant outside every docstring. Counting any file whose text contains
    "README" gave 13, because a docstring explaining why a published count was wrong
    mentions the README it was published in - including one this round added.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        return False
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        carries_a_docstring = (
            ast.Module,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
        if isinstance(node, carries_a_docstring) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and "README" in node.value
        for node in ast.walk(tree)
    )


def test_the_products_that_read_their_own_readme_are_counted_honestly():
    """The index says six of twenty, so that has to be six.

    A figure about how well the repository checks itself is the one it has no excuse
    for getting wrong, and this one has now been wrong twice in one sitting: a
    reviewer counted nine, a first version of this test counted twelve by matching the
    word "README" anywhere, and the same rule counted thirteen once a docstring added
    this round mentioned one. Six files open a README.

    The rest pin their figures in test code, which checks the number against the data
    and not the prose against the number - agri-desk's suite asserts 436, 422 and 2
    against the corpus and would not have noticed its README saying 427, which is
    exactly what it said.
    """
    slugs = sorted(
        d.name for d in PRODUCTS.iterdir() if d.is_dir() and re.fullmatch(r"\d\d_[a-z-]+", d.name)
    )
    sources = [
        path
        for path in list((ROOT / "tests").rglob("*.py")) + list(PRODUCTS.rglob("tests/**/*.py"))
        # This file is the index cross-check, not a product's own check.
        if path.name != Path(__file__).name
    ]
    checked = set()
    for path in sources:
        if not _reads_a_readme(path):
            continue
        parts = path.relative_to(ROOT).parts
        if len(parts) > 1 and parts[0] == "products" and parts[1] in slugs:
            checked.add(parts[1])
        text = path.read_text(encoding="utf-8", errors="replace")
        for slug in slugs:
            if slug in text:
                checked.add(slug)
    assert len(checked) == 6, sorted(checked)
    assert "**Six** of the twenty" in INDEX.read_text(encoding="utf-8"), (
        f"{len(checked)} products open their own README; the index states a different number"
    )
