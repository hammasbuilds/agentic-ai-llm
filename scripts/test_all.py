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

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREES = ("projects", "products")
#: Per-suite ceiling. The comment here used to read "the slowest honest suite takes
#: ~30s", which was stale by 3.5x - three suites run over 70s and the products tree
#: takes about eight minutes in total. A ceiling 2.7x the slowest real suite kills a
#: suite that grows and reports it as HUNG, so the ceiling is 600s and the runner
#: prints its own headroom at the end rather than trusting a number written here.
TIMEOUT = 600


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


#: Every environment variable that decides whether a suite runs or skips. `REPOS_ROOT`
#: defaults to the folder this checkout sits in, so on a developer machine with a tree
#: of checkouts beside it, `20_driftwatch` runs 21 tests that a fresh clone skips - and
#: its README said "72 passed", a number true on exactly one machine. The HF cache is
#: the same shape for the swebench and devign slices.
FRESH_ENV = ("REPOS_ROOT", "HF_HOME", "HF_HUB_CACHE")


def fresh_environment(empty: Path) -> dict[str, str]:
    """The environment a reader has on a fresh clone: these inputs absent.

    Pointed at an empty directory rather than unset, because unsetting `REPOS_ROOT`
    falls back to the folder this checkout sits in, which on this machine is the tree
    of checkouts the gate is trying to exclude.
    """
    empty.mkdir(parents=True, exist_ok=True)
    return {name: str(empty) for name in FRESH_ENV}


def run(package: Path, env: dict[str, str] | None = None) -> tuple[str, dict[str, int], str, float]:
    """Return (outcome, pytest's counts, detail, seconds) for one package."""
    began = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=package,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            check=False,
            env={**os.environ, **env} if env else None,
        )
    except subprocess.TimeoutExpired:
        # A hung suite is one package's problem and must not become every other
        # package's. This used to raise out of main(), abandoning the twenty-one
        # suites after it and printing a traceback where a result belonged.
        return "HUNG", {}, f"no output in {TIMEOUT}s; killed", time.monotonic() - began
    elapsed = time.monotonic() - began
    blob = proc.stdout + proc.stderr
    tally = counts(blob)
    if proc.returncode == 0:
        # A suite where everything skipped is not a suite that passed. It exits
        # 0, and calling that green is how a package stops being tested without
        # anyone finding out.
        if tally.get("passed", 0) == 0 and tally.get("skipped", 0):
            return "SKIPPED", tally, f"{tally['skipped']} skipped, nothing ran", elapsed
        return "ok", tally, "", elapsed
    detail = next(
        (
            ln.strip()
            for ln in blob.splitlines()
            if "ModuleNotFoundError" in ln or "ImportError" in ln or "Error" in ln
        ),
        f"exit {proc.returncode}",
    )
    return (
        "FAIL",
        tally,
        (f"{tally.get('failed', 0)} failed, {tally.get('error', 0)} errors | {detail[:70]}"),
        elapsed,
    )


#: Where --write-counts puts what every suite really did. The READMEs quote "N passed"
#: and `tests/test_documented_counts.py` used to check that against what pytest
#: COLLECTS, which is passed + skipped: a README promising 35 passing tests on a suite
#: that passes 32 and skips 3 was green. Collection cannot tell the two apart, and
#: running all 32 suites inside that test would add ten minutes to the root suite, so
#: the real split is recorded here by the runner that already measures it.
COUNTS = ROOT / "tests" / "fixtures" / "suite_counts.json"


def _write_counts(
    trees: tuple[str, ...],
    measured: dict[str, dict[str, int]],
    broken: list[tuple[str, str]],
) -> None:
    """Record what every suite really did, for the READMEs to be checked against."""
    if broken:
        # A fixture frozen from a red sweep would be the wrong numbers, checked
        # against for weeks.
        print("\nnot writing counts: the sweep was not green")
        return
    if set(trees) != set(TREES):
        print(f"\nnot writing counts: {trees} is not the whole tree")
        return
    COUNTS.parent.mkdir(parents=True, exist_ok=True)
    COUNTS.write_text(
        json.dumps(
            {
                "measured": time.strftime("%Y-%m-%d"),
                "fresh": sorted(FRESH_ENV),
                "note": (
                    "What every suite really did on a fresh clone, recorded by "
                    "scripts/test_all.py --write-counts with the variables in 'fresh' "
                    "pointed at an empty directory. The READMEs quote these, so they "
                    "are the numbers a reader reproduces rather than the ones this "
                    "machine happens to produce - 20_driftwatch ran 21 more tests here "
                    "than anywhere else, and its README said so."
                ),
                "suites": dict(sorted(measured.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {COUNTS.relative_to(ROOT)}")


def main() -> int:
    flags = {"--write-counts", "--fresh"}
    argv = [a for a in sys.argv[1:] if a not in flags]
    write_counts = "--write-counts" in sys.argv[1:]
    # Recording counts implies a fresh run: a figure a reader cannot reproduce is not
    # the figure to publish, and this is the only thing that decides which gets written.
    fresh = write_counts or "--fresh" in sys.argv[1:]
    trees = tuple(argv) or TREES
    packages = suites(trees)
    if not packages:
        raise SystemExit(f"no packages with tests/ under {trees}")

    env = fresh_environment(ROOT / ".test_all_fresh") if fresh else None
    print(f"{len(packages)} packages with test suites")
    if env:
        print(f"  {', '.join(FRESH_ENV)} pointed at an empty directory (a fresh clone)")
    print()
    started = time.time()
    total = skipped = 0
    broken: list[tuple[str, str]] = []

    slowest: tuple[float, str] = (0.0, "-")
    measured: dict[str, dict[str, int]] = {}
    for package in packages:
        outcome, tally, detail, elapsed = run(package, env)
        count = tally.get("passed", 0)
        total += count
        skipped += tally.get("skipped", 0)
        label = f"{package.parent.name}/{package.name}"
        ran = f"{count:>5} ran" + (f" +{tally['skipped']} skip" if tally.get("skipped") else "")
        print(
            f"  {label:<34}{ran:>16}   {outcome}" + (f"   {detail}" if detail else ""), flush=True
        )
        slowest = max(slowest, (elapsed, label))
        measured[label] = {
            "passed": count,
            "skipped": tally.get("skipped", 0),
            "outcome": outcome,
        }
        if outcome != "ok":
            broken.append((label, detail))

    print()
    # The headline is what RAN. Skips are reported beside it rather than folded
    # in, because a suite gated on a path that does not exist on this machine
    # contributes nothing and must not be quoted as though it did.
    print(
        f"{total:,} tests ran across {len(packages)} packages in "
        f"{time.time() - started:.0f}s" + (f", {skipped} skipped" if skipped else "")
    )
    # The ceiling's headroom, measured on this run. A suite is killed and reported as
    # HUNG at TIMEOUT, so how close the slowest one is to it is worth knowing before a
    # growing suite starts being reported as broken rather than slow.
    seconds, name = slowest
    headroom = TIMEOUT / max(seconds, 1)
    print(f"  slowest suite {name} at {seconds:.0f}s, {headroom:.1f}x under the {TIMEOUT}s ceiling")
    if write_counts:
        _write_counts(trees, measured, broken)
    if broken:
        print(f"\n{len(broken)} package(s) not green:")
        for label, detail in broken:
            print(f"  {label}: {detail}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
