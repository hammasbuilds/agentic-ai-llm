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

import importlib.util
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


def test_a_partial_run_leaves_the_committed_file_alone():
    """The destructive half, driven by making one product fail.

    `capture()` is monkeypatched to raise for a single product; the script must report
    the failure, exit non-zero, and not write. Previously it wrote twenty error stubs
    and exited 0.
    """
    spec = importlib.util.spec_from_file_location("capture_probe", CAPTURE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_probe"] = module
    for src in sorted(PRODUCTS.glob("*/src")):
        sys.path.insert(0, str(src))
    spec.loader.exec_module(module)

    before = RUNS.read_bytes()
    real = module.capture
    module.capture = lambda product: (
        (_ for _ in ()).throw(RuntimeError("probe"))
        if (product.name == "01_revenue-desk")
        else real(product)
    )
    try:
        with pytest.raises(SystemExit) as exited:
            module.main()
        assert exited.value.code == 1
    finally:
        module.capture = real
        # Put it back BEFORE asserting. The first version asserted first, so when the
        # guard was corrupted to prove this test bites, the test failed and left
        # runs.json overwritten - a test about not destroying an artefact, destroying
        # it on the way to reporting that.
        written = RUNS.read_bytes()
        if written != before:
            RUNS.write_bytes(before)
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
