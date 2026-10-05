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
    """Executed lines, keyed by repo-relative posix path."""

    lines: dict[str, set[int]]

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
            return Coverage(lines={})
        raw = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return Coverage(lines={})
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
