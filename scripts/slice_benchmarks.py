"""Re-slice the committed benchmark data from a full Hugging Face cache.

`data/benchmarks/` holds the columns these apps read, so a fresh clone can run the
measurements the README says are reproducible offline. This writes them.

It is a script rather than a test fixture because it needs the real datasets: run it on
a machine that has them, commit what it writes, and `tests/test_hermetic.py` checks the
result. Nothing here is a measurement — the row counts it prints are the contract that
test asserts.

    python scripts/slice_benchmarks.py

Refuses rather than writing a truncated slice if a source is missing, because a slice
with the right filename and the wrong number of rows is worse than no slice: every rate
computed from it would be over a denominator nobody chose.
"""

from __future__ import annotations

import glob
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps._engine import hf_cache  # noqa: E402

OUT = ROOT / "data" / "benchmarks"

#: (destination, cache glob, columns to keep or None to copy whole, expected rows)
SLICES = (
    (
        "swebench_lite_test.parquet",
        "datasets--princeton-nlp--SWE-bench_Lite/snapshots/*/data/test-*.parquet",
        ["instance_id", "repo", "base_commit", "problem_statement", "hints_text", "patch"],
        300,
    ),
    (
        "devign_test.parquet",
        "datasets--google--code_x_glue_cc_defect_detection/snapshots/*/data/test-*.parquet",
        ["func", "target"],
        2732,
    ),
    ("mbpp.jsonl", "datasets--Muennighoff--mbpp/snapshots/*/data/mbpp.jsonl", None, 974),
    (
        "sanitized-mbpp.json",
        "datasets--Muennighoff--mbpp/snapshots/*/data/sanitized-mbpp.json",
        None,
        427,
    ),
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    for name, pattern, columns, expected in SLICES:
        hits = [
            hit for root in hf_cache.cache_roots() for hit in sorted(glob.glob(str(root / pattern)))
        ]
        if not hits:
            missing.append((name, pattern))
            continue
        source = Path(hits[0])

        if columns is None:
            shutil.copyfile(source, OUT / name)
            rows = sum(1 for _ in (OUT / name).open(encoding="utf-8")) if name.endswith("l") else 0
        else:
            import pandas as pd

            frame = pd.read_parquet(source)[columns]
            if len(frame) != expected:
                print(
                    f"  {name}: source has {len(frame)} rows, expected {expected}; not written",
                    file=sys.stderr,
                )
                missing.append((name, "row count"))
                continue
            frame.to_parquet(OUT / name, compression="zstd", index=False)
            rows = len(frame)

        size = (OUT / name).stat().st_size / 1e6
        print(f"  {name:30} {size:5.2f} MB  {rows or 'copied'}")

    if missing:
        print("\nnot written:", file=sys.stderr)
        for name, why in missing:
            print(f"  {name}: no source matching {why}", file=sys.stderr)
        print(
            "\nRun this on a machine with the full datasets cached. A truncated slice "
            "is worse than none.",
            file=sys.stderr,
        )
        return 1

    total = sum(f.stat().st_size for f in OUT.glob("*") if f.suffix != ".md")
    print(f"  {'TOTAL':30} {total / 1e6:5.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
