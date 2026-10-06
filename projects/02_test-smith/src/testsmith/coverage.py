"""Line coverage with the standard library, so the comparison costs no dependency.

The point of measuring coverage here is not to report it. It is to split
surviving mutants into two very different groups:

  - survivors on lines the tests never executed  - unsurprising, and a coverage
    problem
  - survivors on lines the tests *did* execute   - the interesting ones: the
    test ran the code, the code was wrong, and nothing failed

The second group is what a coverage percentage cannot show you, and it is the
reason mutation testing exists.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Injected into the workspace and run instead of pytest directly. Kept as a
# string so the package ships one file rather than a data file it must locate.
_TRACER = """
import json, os, sys, threading

TARGET_ROOT = os.path.abspath(sys.argv[1])
OUT = sys.argv[2]
covered = {}

def _trace(frame, event, arg):
    if event != "call":
        return None
    path = frame.f_code.co_filename
    if not path.startswith(TARGET_ROOT):
        return None
    return _line

def _line(frame, event, arg):
    if event == "line":
        path = frame.f_code.co_filename
        covered.setdefault(path, set()).add(frame.f_lineno)
    return _line

sys.argv = [sys.argv[0], "-q", "-p", "no:cacheprovider", "--no-header"]
sys.settrace(_trace)
threading.settrace(_trace)
try:
    import pytest
    code = pytest.main(sys.argv[1:])
finally:
    sys.settrace(None)
    threading.settrace(None)

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({k: sorted(v) for k, v in covered.items()}, fh)

raise SystemExit(int(code))
"""


@dataclass
class Coverage:
    """Executed lines, keyed by repo-relative posix path.

    `failure` is why nothing was measured, and it is the difference between "the
    suite executed no mutable line" and "the trace never ran". Both used to be
    `Coverage(lines={})`: a crash, a timeout or a missing output file returned the
    same empty mapping as a clean measurement of nothing, and the report printed
    "none - every executed line that could be mutated was checked" over zero
    observations and exited 0.

    What this does NOT catch is a *partial* loss. A suite that calls
    `sys.settrace(None)` part-way - which pytest-cov, xdist and any debugger do -
    keeps the lines traced before that point and loses the rest, and from the outside
    a line whose tracing was switched off is indistinguishable from a line that was
    never executed. Measured here: a one-test suite calling `settrace(None)` traced 6
    lines against 7 for the same suite without it, so the loss is real and silent. The
    consequence is that `survivors_on_covered_lines` can under-report and
    `survivors_off_covered_lines` over-report, in the direction that makes the suite
    look better. There is no fix from inside the tracer; it is a reason to read the
    unrestricted score beside the restricted one, which the report prints.
    """

    lines: dict[str, set[int]]
    failure: str = ""

    @property
    def measured(self) -> bool:
        """Whether the trace ran at all. False is not the same as "covered nothing"."""
        return not self.failure

    def executed(self, path: str, line: int) -> bool:
        return line in self.lines.get(path, ())

    def covered_lines(self, path: str) -> int:
        return len(self.lines.get(path, ()))

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.lines.values())


def measure(
    interpreter: str, workspace: Path, env: dict[str, str], timeout: float = 600
) -> Coverage:
    """Run the suite once under a tracer and collect executed lines.

    Returns empty coverage rather than raising if tracing fails - the mutation
    run is still valid without it, just less informative.
    """
    script = workspace / "_testsmith_trace.py"
    out = workspace / "_testsmith_cov.json"
    script.write_text(_TRACER, encoding="utf-8")
    try:
        subprocess.run(
            [interpreter, str(script), str(workspace), str(out)],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if not out.exists():
            return Coverage(lines={}, failure="the trace wrote no output file")
        raw = json.loads(out.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return Coverage(lines={}, failure=f"the suite did not finish within {timeout}s")
    except Exception as exc:  # noqa: BLE001 - any failure here is "not measured"
        return Coverage(lines={}, failure=f"{type(exc).__name__}: {exc}")
    finally:
        script.unlink(missing_ok=True)
        out.unlink(missing_ok=True)

    lines: dict[str, set[int]] = {}
    for abs_path, nums in raw.items():
        try:
            rel = Path(abs_path).resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            continue
        lines[rel] = set(nums)
    return Coverage(lines=lines)
