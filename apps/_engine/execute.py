"""Run a candidate solution against a task's tests, in a separate process with a timeout.

Shared by every project in this lab, because the thing that makes a code benchmark
reproducible is not the prompt - it is the execution rule. How code is extracted from a
model response and how it is run decides the score more than the model does.

Outcomes stay separated rather than collapsing into pass/fail:

- `pass`    - all tests held
- `fail`    - an assertion failed, the honest way to be wrong
- `error`   - any other exception
- `timeout` - did not finish

`fail` and `error` both count as rejected, but only `fail` means the tests actually tested
something. A candidate caught by crashing would have survived behind a guard clause.
"""

from __future__ import annotations

import re
import secrets
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 10.0

# Solution first, then setup, then tests. Setup sometimes instantiates classes the
# solution defines, so running it first raises NameError on perfectly good code.
#
# The success marker is a fresh random token per run, and the pass condition is that it
# is the LAST line of stdout. Both halves are necessary, and the fixed marker this
# replaced was a false-accept channel in the harness itself:
#
#     candidate: print("__OK__")          tests: assert add(2, 3) == 5
#     -> the assert raises NameError, exit code 1, and the run scored `pass`
#        because "__OK__" was already in stdout.
#
# A candidate returning 0 for every input scored `pass` the same way. That is exactly
# the failure App 02 exists to measure, sitting in the thing doing the measuring, and
# every number any app here reports depends on this function being right. A nonce
# cannot be printed by code that has never seen it, and requiring it last means output
# after the tests cannot stand in for the tests having run.
_RUNNER = """\
import sys
{code}

{setup}

{tests}
print({marker!r})
"""

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class Outcome:
    status: str
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def extract_code(raw: str) -> str:
    """Pull code out of a model response.

    Permissive on purpose: a fenced block if there is one, otherwise the whole response.
    Stricter rules score the same generations far lower, and that variance is a property
    of the harness rather than of the model.
    """
    if not raw:
        return ""
    m = _FENCE.search(raw)
    return (m.group(1) if m else raw).strip()


def run(code: str, tests, setup: str = "", timeout: float = TIMEOUT) -> Outcome:
    if isinstance(tests, str):
        tests = [tests]
    marker = f"__OK__{secrets.token_hex(8)}__"
    src = _RUNNER.format(code=code, setup=setup, tests="\n".join(tests), marker=marker)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "candidate.py"
        # newline="" disables Windows LF->CRLF translation. Source that already contains
        # CRLF would otherwise become CR CR LF and break backslash line-continuations,
        # turning valid code into a SyntaxError.
        with f.open("w", encoding="utf-8", newline="") as handle:
            handle.write(src)
        try:
            r = subprocess.run(
                [sys.executable, str(f)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=tmp,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Outcome("timeout")
        except OSError as exc:
            return Outcome("error", f"spawn failed: {exc}")

    # Last line, not anywhere: anything the candidate printed after the tests would
    # otherwise stand in for the tests having run.
    lines = [line for line in (r.stdout or "").splitlines() if line.strip()]
    if lines and lines[-1].strip() == marker:
        return Outcome("pass")
    err = (r.stderr or "").strip()
    last = err.rsplit("\n", 1)[-1] if err else ""
    if "AssertionError" in err:
        return Outcome("fail", last)
    return Outcome("error", last[:200])


def run_many(jobs: list[tuple], workers: int = 6) -> list[Outcome]:
    """Each job is (code, tests, setup). Threads, since the work is in subprocesses."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda j: run(*j), jobs))
