"""Where benchmark data comes from, and in what order.

One implementation, because there were three. `datasets.py`, `swebench_data.py` and
`apps/03_vuln_baseline/app.py` each had their own copy of "look in HF_HUB_CACHE, then
HF_HOME, then ~/.cache/huggingface/hub", and all three had the same defect: the default
was appended *underneath* the overrides rather than replaced by them. So HF_HOME and
HF_HUB_CACHE were extra search paths, pointing one at an empty directory isolated
nothing, and every check of whether the suite could run offline was reading the real
cache. A suite needing 1.5 GB of downloads passed as hermetic on the one machine that
had them.

Two things follow from fixing it.

**An override replaces the default.** Set either variable to an empty directory and
`cache_roots()` returns only that directory, which is what makes hermeticity testable
at all.

**There is a committed fallback.** `data/benchmarks/` holds the columns these apps
actually read, sliced out of the public datasets and committed - 2.8 MB, the same order
as `data/trees`, which is committed for exactly this reason. The order is: an explicit
override, then the Hugging Face cache, then the committed slice. So a fresh clone can
run the measurements the README says are reproducible offline, and a machine with the
full datasets still uses them.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

#: Committed slices, relative to the repository root.
BENCHMARKS = Path(__file__).resolve().parents[2] / "data" / "benchmarks"


def cache_roots() -> list[Path]:
    """Hugging Face cache locations. An override replaces the default, never adds to it."""
    if env := os.environ.get("HF_HUB_CACHE"):
        return [Path(env)]
    if env := os.environ.get("HF_HOME"):
        return [Path(env) / "hub"]
    return [Path.home() / ".cache" / "huggingface" / "hub"]


def find_in_cache(pattern: str) -> Path | None:
    """The first file matching `pattern` under any cache root, or None."""
    for root in cache_roots():
        hits = sorted(glob.glob(str(root / pattern)))
        if hits:
            return Path(hits[0])
    return None


def committed(name: str) -> Path | None:
    """A committed slice by filename, or None when it is not there.

    Returning None rather than raising keeps the caller's error message about the
    dataset it wanted rather than about this directory.
    """
    found = BENCHMARKS / name
    return found if found.exists() else None


def resolve(pattern: str, fallback: str) -> Path | None:
    """The cached dataset if present, else the committed slice.

    That order matters: a machine with the full download should use it, because the
    slice carries only the columns these apps read and a future measurement may want
    another one.
    """
    return find_in_cache(pattern) or committed(fallback)
