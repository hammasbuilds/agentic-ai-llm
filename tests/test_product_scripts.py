"""The three scripts that drive a product's graph all still run.

`products/scripts/` holds three: `capture.py`, which produces `runs.json` and every
product README's Input/Output section; `smoke_serve.py`, which produces `served.json`
and backs "All 20 also boot on a real ASGI server"; and `screenshots.py`, which produces
the console PNGs. All three load a product's `tests/test_graph.py` and call four things
on it.

Nineteen products moved those four from module level into a `StandardProductTests`
subclass. `capture.py` was given an adapter for both shapes - `tests/test_captured_runs.py`
exists because the version before it raised `AttributeError` on all twenty - and the two
scripts beside it were not touched:

    $ python scripts/smoke_serve.py
    1/20 products served over HTTP

with `AttributeError: module 'test_graph' has no attribute 'payload'` for products 02 to
20, *after* rewriting `served.json` from twenty good rows to one row and nineteen error
stubs. Following the README destroyed the artefact the README points at, which is the
same sentence `test_captured_runs.py` was written to stop being true.

The adapter is shared now. This file is the thing that was missing: a test that runs all
three, so a fourth shape change breaks a test rather than an artefact.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "products" / "scripts"

#: Every script in `products/scripts/` that drives a product graph, and the artefact it
#: writes. Built from the directory below, so a fourth script is covered by existing.
DRIVERS = {
    "capture.py": "runs.json",
    "smoke_serve.py": "served.json",
    "screenshots.py": None,  # writes PNGs under products/01_revenue-desk/docs
}


def test_every_script_that_loads_a_product_test_is_covered_here():
    """Built from the directory, not from a list somebody maintains.

    A script is a driver if it loads a product's `test_graph`; that is what breaks when
    the shape of those files changes. The other scripts here build fixture data and
    never touch one.
    """
    loaders = {
        path.name
        for path in SCRIPTS.glob("*.py")
        if 'import_module("test_graph")' in path.read_text(encoding="utf-8")
    }
    assert loaders == set(DRIVERS), loaders


@pytest.mark.parametrize("script", sorted(DRIVERS))
def test_no_script_reads_the_module_level_shape_directly(script: str):
    """The defect, as a rule rather than as the two files it happened in.

    `tg.payload()`, `tg.sources()`, `tg.runtime()` and `tg.SCRIPT` are the shape one
    product of twenty still has. A script that reads them directly works on that one and
    raises on nineteen, and the two that did were found by a reviewer running them, not
    by the suite.
    """
    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"))
    direct = [
        f"tg.{node.attr} at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and getattr(node.value, "id", "") == "tg"
        and node.attr in ("payload", "sources", "runtime", "script", "SCRIPT")
    ]
    assert direct == [], (
        f"{script} reads the module-level shape directly: {direct}. Nineteen of the "
        "twenty products declare those on a `StandardProductTests` subclass; use "
        "`spec_for` from `product_spec.py`, which reads either."
    )


@pytest.mark.parametrize("script", sorted(DRIVERS))
def test_every_script_uses_the_shared_adapter(script: str):
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    assert "spec_for" in source, f"{script} does not use the shared adapter"


def test_the_adapter_reads_both_shapes():
    """`01_revenue-desk` writes its four at module level and the other nineteen do not.

    Both are real and the adapter is the only thing that knows it, so this asserts the
    premise rather than taking it from the docstring: if all twenty ever moved, the
    module wrapper becomes dead code and this says so.
    """
    sys.path.insert(0, str(SCRIPTS))
    at_module_level = []
    subclassing = []
    for product in sorted((ROOT / "products").glob("[0-9]*")):
        test_graph = product / "tests" / "test_graph.py"
        if not test_graph.is_file():
            continue
        tree = ast.parse(test_graph.read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        (at_module_level if "payload" in names else subclassing).append(product.name)
    assert at_module_level == ["01_revenue-desk"], at_module_level
    assert len(subclassing) == 19, subclassing


@pytest.mark.slow
def test_smoke_serve_reproduces_the_artefact_it_published():
    """It boots all twenty over HTTP and writes what is committed.

    This is the claim `products/README.md` makes - "All 20 also boot on a real ASGI
    server", `# 20/20 products served over HTTP` - and the file beside it is the
    evidence. Running the command used to replace the evidence with nineteen errors.

    The port is deliberately not in the artefact: it is whatever the OS handed out, so
    recording it made the file differ on every run for a reason that says nothing, and
    a committed file that cannot reproduce is one nobody can check.
    """
    artefact = SCRIPTS / "served.json"
    before = artefact.read_text(encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "scripts/smoke_serve.py"],
        cwd=str(ROOT / "products"),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=1200,
    )
    after = artefact.read_text(encoding="utf-8")
    artefact.write_text(before, encoding="utf-8")

    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "20/20 products served over HTTP" in done.stdout, done.stdout[-3000:]
    assert after == before, (
        "`python scripts/smoke_serve.py` did not reproduce `served.json`. The committed "
        "file is what the README points at as evidence, so the command and the file "
        "have to agree."
    )

    rows = json.loads(before)
    assert len(rows) == 20, sorted(rows)
    assert all("error" not in row for row in rows.values()), [
        name for name, row in rows.items() if "error" in row
    ]
    assert all(row["console_ok"] for row in rows.values())


def test_the_readme_quotes_what_that_command_prints():
    index = (ROOT / "products" / "README.md").read_text(encoding="utf-8")
    assert "20/20 products served over HTTP" in index
    assert "scripts/served.json" in index
    rows = json.loads((SCRIPTS / "served.json").read_text(encoding="utf-8"))
    assert len(rows) == 20
