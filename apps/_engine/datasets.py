"""MBPP and HumanEval, loaded from the local Hugging Face cache.

Both benchmarks describe a task, give a reference solution and give a way to check a
candidate. They disagree about almost everything else - MBPP hands you three asserts and
a plain-English sentence, HumanEval hands you a function signature with a docstring and a
`check()` harness - so the loader normalises them into one shape and every project here
runs against both without caring which is which.

No network. Both are already cached and together weigh about 1 MB.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_CALLED = re.compile(r"assert\s+(?:not\s+)?([A-Za-z_]\w*)\s*\(")


@dataclass(frozen=True)
class Task:
    """One problem, normalised across benchmarks."""

    benchmark: str  # "mbpp" | "humaneval"
    task_id: str
    prompt: str  # what the model is asked to implement
    reference: str  # the solution the benchmark calls correct
    entry_point: str  # the function under test
    tests: tuple[str, ...]  # assert statements, or a single check() call
    setup: str = ""  # runs after the solution, before the tests

    @property
    def is_mbpp(self) -> bool:
        return self.benchmark == "mbpp"


def _cache_roots() -> list[Path]:
    roots = []
    if env := os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(env))
    if env := os.environ.get("HF_HOME"):
        roots.append(Path(env) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


def _find(pattern: str) -> Path | None:
    for root in _cache_roots():
        hits = sorted(glob.glob(str(root / pattern)))
        if hits:
            return Path(hits[0])
    return None


def load_mbpp(limit: int | None = None, split: str = "full") -> list[Task]:
    """MBPP, or its hand-verified subset.

    `sanitized` is the 427 problems the authors re-checked by hand, and it ships in the
    same snapshot as a JSON array rather than JSON Lines. Three places in this repository
    quoted a number for that split while nothing could load it: the app's docstring, its
    About panel and the root README. The data was there the whole time.
    """
    if split not in {"full", "sanitized"}:
        raise ValueError(f"unknown MBPP split {split!r}; expected full or sanitized")
    if split == "sanitized":
        path = _find("datasets--Muennighoff--mbpp/snapshots/*/data/sanitized-mbpp.json")
        if path is None:
            raise FileNotFoundError("the sanitized MBPP split is not in the local cache")
        rows = json.loads(path.read_text(encoding="utf-8"))
        # The sanitized rows call the problem statement `prompt` and carry their imports
        # in `test_imports`, where the full split uses `text` and `test_setup_code`.
        lines = [
            json.dumps(
                {
                    "task_id": r["task_id"],
                    "text": r.get("prompt", ""),
                    "code": r["code"],
                    "test_list": r["test_list"],
                    "test_setup_code": chr(10).join(r.get("test_imports") or []),
                }
            )
            for r in rows
        ]
    else:
        path = _find("datasets--Muennighoff--mbpp/snapshots/*/data/mbpp.jsonl")
        if path is None:
            raise FileNotFoundError("MBPP not in the local Hugging Face cache")
        lines = path.read_text(encoding="utf-8").splitlines()

    out: list[Task] = []
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        tests = tuple(r["test_list"])
        entry = next((m.group(1) for t in tests if (m := _CALLED.search(t))), "")
        if not entry:
            continue
        out.append(
            Task(
                benchmark="mbpp" if split == "full" else "mbpp-sanitized",
                task_id=f"mbpp/{r['task_id']}",
                prompt=r["text"],
                reference=r["code"],
                entry_point=entry,
                tests=tests,
                setup=r.get("test_setup_code") or "",
            )
        )
        if limit and len(out) >= limit:
            break
    return out


def load_humaneval(limit: int | None = None) -> list[Task]:
    path = _find("datasets--openai--openai_humaneval/snapshots/*/openai_humaneval/*.parquet")
    if path is None:
        raise FileNotFoundError("HumanEval not in the local Hugging Face cache")
    import pandas as pd

    frame = pd.read_parquet(path)
    out: list[Task] = []
    for _, row in frame.iterrows():
        out.append(
            Task(
                benchmark="humaneval",
                task_id=row["task_id"],
                # The prompt IS the signature plus docstring; that is the task statement.
                prompt=row["prompt"],
                reference=row["prompt"] + row["canonical_solution"],
                entry_point=row["entry_point"],
                # HumanEval ships one `check(fn)` harness rather than loose asserts.
                tests=(row["test"], f"check({row['entry_point']})"),
            )
        )
        if limit and len(out) >= limit:
            break
    return out


def load(benchmark: str = "mbpp", limit: int | None = None) -> list[Task]:
    if benchmark == "mbpp":
        return load_mbpp(limit)
    if benchmark == "mbpp-sanitized":
        return load_mbpp(limit, split="sanitized")
    if benchmark == "humaneval":
        return load_humaneval(limit)
    raise ValueError(f"unknown benchmark {benchmark!r}; expected mbpp, mbpp-sanitized or humaneval")
