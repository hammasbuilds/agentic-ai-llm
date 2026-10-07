"""The byte-order-mark helper is hand-copied into three packages, byte for byte.

`projects/*` are deliberately independent - each has its own `pyproject.toml`, its own
suite, and no shared library - so three copies of a twenty-line helper is the
architecture rather than an accident. What is not acceptable is three copies of a
*defect*, and that is what happened: all three mapped the little-endian mark to
`utf-16-le`, which is the one codec that does NOT consume the mark, so an Excel
"Unicode Text" export was accepted and then read with an invisible `﻿` glued to
the front of its first field. Three tools, three different wrong answers on data whose
UTF-8 twin was right.

The remedy for duplication you cannot remove is to assert it. If a fix lands in one
copy and not the others, this fails and names which.

`data/benchmarks/README.md` records the same shape one layer down: the HF cache-root
logic lived in three places and "none of them could be pointed at an empty directory",
so the suite was never hermetic and nothing could tell.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The three files holding the helper, and the package each belongs to.
COPIES = {
    "csv-analyst": ROOT / "projects/08_csv-analyst/src/csvanalyst/profile.py",
    "log-detective": ROOT / "projects/09_log-detective/src/detective/cli.py",
    "contract-reader": ROOT / "projects/10_contract-reader/src/contractreader/cli.py",
}

#: The names that have to be identical in every copy.
SHARED = ("BOM_ENCODINGS", "declared_encoding", "_strip_mark")


def _source_of(path: Path, name: str) -> str:
    """The source of one top-level definition or assignment, normalised."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == name for target in node.targets
        ):
            return ast.get_source_segment(text, node) or ""
    return ""


def test_all_three_copies_are_present():
    """A sweep over an empty mapping passes."""
    assert len(COPIES) == 3
    for label, path in COPIES.items():
        assert path.is_file(), label
        assert "BOM_ENCODINGS" in path.read_text(encoding="utf-8"), label


@pytest.mark.parametrize("name", SHARED)
def test_every_copy_of_the_helper_is_identical(name: str):
    bodies = {label: _source_of(path, name) for label, path in COPIES.items()}
    missing = sorted(label for label, body in bodies.items() if not body)
    assert not missing, f"{name} is absent from {missing}"

    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        f"{name} differs between copies - a fix landed in one and not the others:\n"
        + "\n\n".join(f"--- {label}\n{body}" for label, body in sorted(bodies.items()))
    )


@pytest.mark.parametrize("label", sorted(COPIES))
def test_the_mark_is_mapped_to_a_codec_that_consumes_it(label: str):
    """The defect, as the one line that caused it.

    Python strips the mark only for the bare `utf-16`/`utf-32` and for `utf-8-sig`.
    `utf-16-le` decodes it as a character, so the mapping must not name an
    explicit-endian codec.
    """
    source = COPIES[label].read_text(encoding="utf-8")
    table = _source_of(COPIES[label], "BOM_ENCODINGS")
    assert table, label
    for forbidden in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
        assert forbidden not in table, (
            f"{label} maps a mark to {forbidden}, which decodes the mark as a "
            "character instead of consuming it"
        )
    assert "_strip_mark" in source, f"{label} does not strip a leftover mark"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig"])
@pytest.mark.parametrize("label", sorted(COPIES))
def test_the_helper_returns_a_codec_that_leaves_no_mark(label: str, encoding: str):
    """Run, not read: decode a marked file with what the helper returns and check the
    first character is the data."""
    import importlib
    import sys

    path = COPIES[label]
    # Imported as part of its package, not by path: these modules use relative
    # imports, so a by-path load raises "attempted relative import with no known
    # parent package".
    src = path.parent.parent
    module_name = f"{path.parent.name}.{path.stem}"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module(module_name)
    finally:
        sys.path.remove(str(src))

    raw = "qty,name\n5,a\n".encode(encoding)
    declared = module.declared_encoding(raw[:4])
    assert declared is not None, (label, encoding)
    text = module._strip_mark(raw.decode(declared))
    assert text.startswith("qty"), (label, encoding, text[:12])
    assert "﻿" not in text, (label, encoding)
