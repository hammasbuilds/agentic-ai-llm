"""One line per finished job, appended to a file you name — and nothing at all otherwise.

OFF unless `AAL_TELEMETRY` holds a path. Every `runtime()` here already falls back to an
in-memory bus and store, so an install that quietly started writing to disk would be the
one component that did not keep that promise.

**This is not the job store.** `cache.py` holds live job state in Redis under a TTL, or in
a dict when Redis is absent — which is right for a page polling its own run, and is gone
on restart and gone when the key expires. This file is the durable record: what ran, how
long it took, which way it travelled, and whether it worked. The console in
`observability/` reads it; nothing else does.

What is recorded is the SHAPE of a run. The app, the outcome, the duration, the transport,
how many items it got through. Not the parameters, not the result, not the error text —
a measurement's parameters can hold a pasted issue report, and an exception message can
hold a path. `tests/test_telemetry.py` asserts that a distinctive parameter put through a
job does not appear in the log it produced.

Three rules: it never raises into the caller, never costs more than a line write, and the
file rotates at 8 MB keeping one generation, so a long-running worker cannot fill a disk.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

#: The variable that switches this on, and the file it names.
ENV = "AAL_TELEMETRY"

#: Rotate past this, keeping one generation: 16 MB worst case.
MAX_BYTES = 8 * 1024 * 1024


def destination() -> Path | None:
    """The file to append to, or None when telemetry is off."""
    raw = (os.environ.get(ENV) or "").strip()
    return Path(raw) if raw else None


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def record(event: dict[str, Any]) -> None:
    """Append one event, if telemetry is on. Never raises.

    Called from the job path, which is async and already handling a failure when it
    reaches the error branch. A telemetry exception there would replace a measurement's
    real error with this module's, so every failure here ends in a return.
    """
    path = destination()
    if path is None:
        return
    try:
        event.setdefault("at", time.time())
        line = json.dumps(event, ensure_ascii=False, default=str)
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError, UnicodeError):
        return


def job(app: str, outcome: str, seconds: float, **fields: Any) -> None:
    """One finished job.

    `outcome` is `done` or `error`. `transport` says whether it went over the bus or ran
    in process, which is the figure this repository's own README is careful about: the
    adapters ship and nothing binds one, so a console showing every run as `inline` is
    showing the truth rather than a misconfiguration.
    """
    record(
        {
            "app": app,
            "outcome": outcome,
            "seconds": round(seconds, 3),
            **{k: v for k, v in fields.items() if v is not None},
        }
    )
