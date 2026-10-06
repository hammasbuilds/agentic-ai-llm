"""Load SWE-bench Lite from the local Hugging Face cache and recover gold file paths.

No network, no repo clones. The parquet is already cached; the gold patch tells us
which files a correct solution touches, which is all the localization experiment needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import hf_cache

HF_REPO = "princeton-nlp/SWE-bench_Lite"
CACHE_DIR_NAME = "datasets--princeton-nlp--SWE-bench_Lite"

# A unified diff names the file twice; the b/ side is the post-image, which is the
# one that exists after a fix (the a/ side is /dev/null for added files).
DIFF_B_PATH = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str
    gold_files: tuple[str, ...]

    @property
    def is_single_file(self) -> bool:
        return len(self.gold_files) == 1


def gold_files_from_patch(patch: str) -> tuple[str, ...]:
    """Files a correct patch modifies, in the order they appear in the diff."""
    found = DIFF_B_PATH.findall(patch or "")
    # /dev/null appears for deletions; drop it and de-duplicate while keeping order.
    seen: dict[str, None] = {}
    for path in found:
        path = path.strip()
        if path and path != "/dev/null":
            seen.setdefault(path, None)
    return tuple(seen)


def find_parquet() -> Path | None:
    """The cached test split, or the committed slice, without importing `datasets`.

    The committed slice carries the six columns this module reads. It is the reason
    `python -m apps._engine.localize_eval` runs on a fresh clone, which the README
    says it does.
    """
    return hf_cache.resolve(
        f"{CACHE_DIR_NAME}/snapshots/*/data/test-*.parquet", "swebench_lite_test.parquet"
    )


def _frame() -> pd.DataFrame:
    """Read the split from cache; fall back to downloading it (1.2 MB)."""
    cached = find_parquet()
    if cached is not None:
        return pd.read_parquet(cached)
    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise FileNotFoundError(
            f"{HF_REPO} is not in the local Hugging Face cache and `datasets` is not "
            "installed, so it cannot be fetched.\n"
            "Fix either one:\n"
            "  pip install datasets        # then it downloads (~1.2 MB)\n"
            "  or set HF_HOME / HF_HUB_CACHE to the cache that already holds it.\n"
            f"Looked in: {', '.join(str(r) for r in hf_cache.cache_roots())}, "
            f"and for a committed slice at {hf_cache.BENCHMARKS}"
        ) from exc
    return load_dataset(HF_REPO, split="test").to_pandas()


def load(limit: int | None = None) -> list[Instance]:
    frame = _frame()
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            Instance(
                instance_id=row["instance_id"],
                repo=row["repo"],
                base_commit=row["base_commit"],
                problem_statement=row["problem_statement"] or "",
                hints_text=row["hints_text"] or "",
                gold_files=gold_files_from_patch(row["patch"]),
            )
        )
        if limit and len(rows) >= limit:
            break
    return rows
