"""Run every sub-project's test suite and report the total.

    python scripts/test_all.py            # everything
    python scripts/test_all.py projects   # just projects/

This repository is a monorepo of independent packages: each of `projects/*` and
`products/*` has its own `pyproject.toml` with its own `pythonpath = ["src"]`,
and each is meant to be runnable on its own. That is a deliberate shape - the
projects claim zero runtime dependencies and are checked that way - but it has
one sharp edge: running `pytest` at the repository root does NOT run them. It
tries to collect them, cannot import their `src` packages, and stops with
dozens of collection errors that look like a broken repository rather than a
layout doing what it was designed to do.

So the root `pyproject.toml` now tells pytest not to descend into them, and
this script is how you run them all. Each suite runs in its own process, from
its own directory, exactly as it would if that package were cloned alone.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREES = ("projects", "products")


def suites(trees: tuple[str, ...]) -> list[Path]:
    found = []
    for tree in trees:
        base = ROOT / tree
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.is_dir() and (entry / "tests").is_dir():
                found.append(entry)
    return found


#: pytest's own counts, from the summary line: "1 failed, 4 passed, 11 skipped in 0.3s".
_OUTCOME = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b")


def counts(blob: str) -> dict[str, int]:
    """Every outcome pytest reported, by name.

    Read with one pattern over the summary line rather than by walking tokens:
    the old version tracked `passed` and `failed` and never looked at `skipped`,
    so a suite that skipped every test reported "0 tests ok" and the total went
    quietly down. A number that can fall without anyone noticing is not a
    measurement.
    """
    found: dict[str, int] = {}
    for line in blob.splitlines():
        for value, name in _OUTCOME.findall(line):
            name = "error" if name == "errors" else name
            found[name] = max(found.get(name, 0), int(value))
    return found


def run(package: Path) -> tuple[str, dict[str, int], str]:
    """Return (outcome, pytest's counts, detail) for one package."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=package, capture_output=True, text=True, errors="replace",
        timeout=900, check=False,
    )
    blob = proc.stdout + proc.stderr
    tally = counts(blob)
    if proc.returncode == 0:
        # A suite where everything skipped is not a suite that passed. It exits
        # 0, and calling that green is how a package stops being tested without
        # anyone finding out.
        if tally.get("passed", 0) == 0 and tally.get("skipped", 0):
            return "SKIPPED", tally, f"{tally['skipped']} skipped, nothing ran"
        return "ok", tally, ""
    detail = next(
        (ln.strip() for ln in blob.splitlines()
         if "ModuleNotFoundError" in ln or "ImportError" in ln or "Error" in ln),
        f"exit {proc.returncode}",
    )
    return "FAIL", tally, (
        f"{tally.get('failed', 0)} failed, {tally.get('error', 0)} errors | {detail[:70]}"
    )


def main() -> int:
    trees = tuple(sys.argv[1:]) or TREES
    packages = suites(trees)
    if not packages:
        raise SystemExit(f"no packages with tests/ under {trees}")

    print(f"{len(packages)} packages with test suites\n")
    started = time.time()
    total = skipped = 0
    broken: list[tuple[str, str]] = []

    for package in packages:
        outcome, tally, detail = run(package)
        count = tally.get("passed", 0)
        total += count
        skipped += tally.get("skipped", 0)
        label = f"{package.parent.name}/{package.name}"
        ran = f"{count:>5} ran" + (f" +{tally['skipped']} skip" if tally.get("skipped") else "")
        print(f"  {label:<34}{ran:>16}   {outcome}"
              + (f"   {detail}" if detail else ""), flush=True)
        if outcome != "ok":
            broken.append((label, detail))

    print()
    # The headline is what RAN. Skips are reported beside it rather than folded
    # in, because a suite gated on a path that does not exist on this machine
    # contributes nothing and must not be quoted as though it did.
    print(
        f"{total:,} tests ran across {len(packages)} packages in "
        f"{time.time() - started:.0f}s"
        + (f", {skipped} skipped" if skipped else "")
    )
    if broken:
        print(f"\n{len(broken)} package(s) not green:")
        for label, detail in broken:
            print(f"  {label}: {detail}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
