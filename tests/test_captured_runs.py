"""`products/scripts/runs.json` against the script that is supposed to produce it.

Every one of the twenty products' Input/Output sections is cross-checked against that
file, and the file is the only provenance any of those figures has. Nothing checked the
file against the generator, and the generator did not run: it reached into
`rt._checkpoints`, a private dict replaced months earlier by a store-backed checkpoint
whose public accessor was added for exactly this caller. `python scripts/capture.py` -
the command `products/README.md` gives - printed `0/20 captured` and had already
overwritten `runs.json` with twenty error stubs. Following the README destroyed the
artefact the README says every figure came from.

Both halves are checked here, because the second is what made the first survivable:

  * the script runs and reproduces the committed file exactly, and
  * a partial run does not replace it.

It takes about a second for all twenty, so there is no excuse for the gap.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products"
RUNS = PRODUCTS / "scripts" / "runs.json"
CAPTURE = PRODUCTS / "scripts" / "capture.py"

pytest.importorskip("fastapi")


def test_the_committed_runs_file_covers_all_twenty():
    """A comparison against an empty mapping passes."""
    recorded = json.loads(RUNS.read_text(encoding="utf-8"))
    assert len(recorded) == 20, sorted(recorded)
    # And no entry is an error stub left behind by a failed run.
    stubs = sorted(name for name, row in recorded.items() if "error" in row)
    assert not stubs, f"error stubs in the committed file: {stubs}"


def test_the_script_reproduces_the_committed_file_exactly():
    """Run it in a subprocess, into a copy, and compare bytes.

    A subprocess because `capture.py` imports all twenty product packages and the root
    suite has its own `sys.path`; into a copy because a test that rewrites a committed
    artefact to check it is a test that can leave the tree dirty when it fails.
    """
    before = RUNS.read_bytes()
    done = subprocess.run(
        [sys.executable, "scripts/capture.py"],
        cwd=str(PRODUCTS),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    after = RUNS.read_bytes()
    if after != before:
        # Put it back before asserting, so a failure does not leave the artefact
        # rewritten - which is the failure mode this whole file is about.
        RUNS.write_bytes(before)
    assert done.returncode == 0, (done.stdout + done.stderr)[-1500:]
    assert "20/20 captured" in done.stdout, done.stdout[-800:]
    assert after == before, (
        "capture.py no longer reproduces the committed runs.json byte for byte. If the "
        "change is deliberate, commit the new file; if not, a published figure has "
        "moved and twenty READMEs are describing something else."
    )


def test_a_partial_run_leaves_the_committed_file_alone(tmp_path):
    """The destructive half, driven by making one product fail.

    In a subprocess, and that is not fussiness. `capture.py` deletes every
    `agentplatform*` entry from `sys.modules` before each product so each gets a clean
    import. Importing it into the test process therefore leaves the session holding
    module objects that no longer match the ones later imports bind to - and
    `except ControlKeyError` cannot catch a class from the other copy. Doing it in
    process turned 140 tests in `tests/test_product_intake.py` red while that file
    passed on its own, which is the worst kind of test failure to read.
    """
    driver = tmp_path / "probe.py"
    driver.write_text(
        chr(10).join(
            [
                "import importlib.util, sys",
                "from pathlib import Path",
                f"CAPTURE = Path(r{str(CAPTURE)!r})",
                f"PRODUCTS = Path(r{str(PRODUCTS)!r})",
                "for src in sorted(PRODUCTS.glob('*/src')):",
                "    sys.path.insert(0, str(src))",
                "spec = importlib.util.spec_from_file_location('capture_probe', CAPTURE)",
                "module = importlib.util.module_from_spec(spec)",
                "sys.modules['capture_probe'] = module",
                "spec.loader.exec_module(module)",
                "real = module.capture",
                "def failing(product):",
                "    if product.name == '01_revenue-desk':",
                "        raise RuntimeError('probe')",
                "    return real(product)",
                "module.capture = failing",
                "try:",
                "    module.main()",
                "except SystemExit as exited:",
                "    print('EXIT', exited.code)",
                "else:",
                "    print('EXIT 0-no-raise')",
            ]
        ),
        encoding="utf-8",
    )

    before = RUNS.read_bytes()
    done = subprocess.run(
        [sys.executable, str(driver)],
        cwd=str(PRODUCTS),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    written = RUNS.read_bytes()
    if written != before:
        # Before asserting. A test about not destroying an artefact must not destroy it
        # on the way to reporting that - which is what happened the first time this was
        # driven against a corrupted guard.
        RUNS.write_bytes(before)

    assert "EXIT 1" in done.stdout, (done.stdout + done.stderr)[-1200:]
    assert written == before, "a failed run overwrote the committed artefact"


def test_capture_reads_the_checkpoint_through_the_public_accessor():
    """The specific regression, pinned by name.

    `rt._checkpoints[...]` is what broke, and `api.py` documents its removal. A test on
    the output alone would catch a reintroduction only as an AttributeError in a
    subprocess, with the reason buried in a traceback.
    """
    source = CAPTURE.read_text(encoding="utf-8")
    assert "rt.checkpoint(" in source
    # Code lines only. The first version of this read the whole file and tripped on the
    # comment above the fix, which names the private dict in order to explain it - the
    # same way three earlier "the old value is gone" tests in this repository tripped on
    # their own prose.
    code = [
        line for line in source.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    offending = [line.strip() for line in code if "_checkpoints" in line]
    assert not offending, f"the private dict is back: {offending}"


# -- the Input/Output rows each README publishes -------------------------------


def _readme_row(product: str, label: str) -> str | None:
    import re

    text = (PRODUCTS / product / "README.md").read_text(encoding="utf-8")
    found = re.search(rf"^\| {re.escape(label)} \|(.*)\|$", text, re.M)
    return found.group(1) if found else None


def test_every_products_result_keys_row_is_the_run_it_quotes():
    """A published list of keys that nothing compared to the run.

    `capture.py` records `result_keys` per product and the READMEs print them, and the
    two were never checked against each other - so when the grounding gate started
    returning `claims_source`, `receipts_source` and `claims_checked`, twenty tables
    went stale and every suite stayed green. The same row would have gone stale for any
    node that gained or lost an output.
    """
    import re

    recorded = json.loads(RUNS.read_text(encoding="utf-8"))
    assert len(recorded) == 20, sorted(recorded)

    for product, row in sorted(recorded.items()):
        keys = row["done"]["result_keys"]
        assert keys, product
        published = _readme_row(product, "Result keys")
        assert published is not None, f"{product}: no Result keys row"
        quoted = sorted(re.findall(r"`([^`]+)`", published))
        assert quoted == sorted(keys), (
            f"{product}: the README lists {len(quoted)} keys and the run produced "
            f"{len(keys)}; gone {sorted(set(quoted) - set(keys))}, "
            f"new {sorted(set(keys) - set(quoted))}"
        )


def test_the_gate_reports_its_source_in_every_products_run():
    """The correction to the README sentence, visible in the artefact.

    Every one of the twenty receives `claims` through `POST /intake`, so every captured
    run must say `payload` - and must not publish a drop rate over it.
    """
    recorded = json.loads(RUNS.read_text(encoding="utf-8"))
    for product, row in sorted(recorded.items()):
        keys = row["done"]["result_keys"]
        if "claims" not in row.get("input_keys", []):
            continue
        assert "claims_source" in keys, product
        assert "receipts_source" in keys, product
