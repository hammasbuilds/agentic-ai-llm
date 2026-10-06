"""Every test count quoted in a README, against what pytest collects.

Five had drifted at once — `02_test-smith` 40 against 39, `01_revenue-desk` 13 against 16,
`20_driftwatch` 41 against 51, `platform` 132 against 127, `projects/README.md` 375 against
386 — and one package's documented command gave 10 *skipped* rather than the 10 passed it
promised, because the environment variable it needs was named nowhere.

A count in a README moves every time a test is added, which is exactly when nobody rereads
the README. Thirty-two packages would be thirty-two tests; this is one.

It runs pytest in collect-only mode per package, a few seconds each, which is the only
answer that cannot itself drift.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: A count beside a `pytest -q` command, in either form the READMEs use:
#: `# 39 tests` counts everything collected; `# 37 passed, 1 skipped` splits it.
QUOTED = re.compile(
    r"pytest -q[^\n#]*#\s*(\d[\d,]*)\s+(tests?|passed)(?:,\s*(\d+)\s+skipped)?",
)

PACKAGES = sorted(
    package
    for tree in ("projects", "products")
    for package in (ROOT / tree).iterdir()
    if (package / "tests").is_dir() and (package / "README.md").is_file()
)


def collected(package: Path) -> int:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(package),
        capture_output=True,
        text=True,
        timeout=900,
    )
    found = re.search(r"(\d+) tests? collected", done.stdout)
    assert found, done.stdout[-500:]
    return int(found.group(1))


#: What every suite really did, recorded by `python scripts/test_all.py --write-counts`.
#: Collection cannot tell a pass from a skip, and this module used to check both forms
#: of claim against it: a README promising "35 passed" on a suite that passes 32 and
#: skips 3 collected 35 and was green. Running all 32 suites here would add ten minutes
#: to the root suite, so the split comes from the runner that already measures it, and
#: `test_the_recorded_counts_still_match_collection` below says when it has gone stale.
COUNTS = ROOT / "tests" / "fixtures" / "suite_counts.json"


def recorded() -> dict[str, dict[str, int]]:
    assert COUNTS.is_file(), (
        f"{COUNTS.relative_to(ROOT)} is missing; run `python scripts/test_all.py --write-counts`"
    )
    return json.loads(COUNTS.read_text(encoding="utf-8"))["suites"]


def label(package: Path) -> str:
    return f"{package.parent.name}/{package.name}"


def test_every_package_with_a_readme_is_swept():
    """A sweep over an empty list passes. Eleven tools, twenty products, the platform."""
    assert len(PACKAGES) == 32, [p.name for p in PACKAGES]


def check(where: str, number: str, kind: str, skipped: str, ran: dict[str, int]) -> None:
    """One quoted count against what the suite really did.

    The two forms mean different things and used to be checked the same way:

    * `# 35 passed` claims 35 tests that pass. Compared against collection it was
      satisfied by 32 passing and 3 skipping, which is the number flattering itself.
    * `# 35 tests` claims 35 tests ran at all, so passes and skips both count.

    A bare `passed` claim on a suite that skips anything is also wrong even when the
    number is right, because a reader runs the command and sees two numbers where the
    README promised one. That form has to split.
    """
    stated = int(number.replace(",", ""))
    passed, skips = ran["passed"], ran["skipped"]
    real = f"the suite passes {passed} and skips {skips}"

    if skipped:
        # Both halves, separately. Comparing `stated + skipped` against
        # `passed + skipped` cancels the skip term on each side, so "37 passed and 1
        # skipped" matched 38 passed and 0 skipped - two wrong numbers summing to the
        # right total, which is the arithmetic this whole module exists to refuse.
        assert (stated, int(skipped)) == (passed, skips), (
            f"{where} says {number} passed and {skipped} skipped; {real}"
        )
        return

    if kind == "passed":
        assert stated == passed, f"{where} says {number} passed; {real}"
        # A bare `passed` claim on a suite that skips anything is wrong even when the
        # number is right: the reader runs the command and sees two numbers where the
        # README promised one.
        assert skips == 0, (
            f"{where} says {number} passed and names no skips, but {real}; "
            f"write `# {passed} passed, {skips} skipped`"
        )
        return

    # `# 35 tests` claims 35 tests ran at all, so passes and skips both count.
    assert stated == passed + skips, f"{where} says {number} tests; {real}"


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_the_readmes_whole_suite_count_is_the_one_pytest_collects(package: Path):
    """Only the count for the package's whole suite.

    A README may also quote per-file counts, which are a different and smaller number.
    What must be right is the headline: the number beside `pytest -q` with no path after
    it, which is the command a reader will actually run.
    """
    readme = (package / "README.md").read_text(encoding="utf-8")
    quoted = QUOTED.findall(readme)
    if not quoted:
        pytest.skip("this README quotes no count for the whole suite")

    ran = recorded()[label(package)]
    for number, kind, skipped in quoted:
        check(f"{package.name}: README", number, kind, skipped, ran)


def test_the_projects_index_totals_the_eleven():
    """`projects/README.md` quotes a total across the tree, which drifts eleven ways."""
    index = (ROOT / "projects" / "README.md").read_text(encoding="utf-8")
    stated = re.search(r"\*\*(\d[\d,]*) tests across the eleven\*\*", index)
    assert stated, "the index no longer states a total"
    ran = recorded()
    # "tests", so passes and skips both count - and the index says so in that word.
    total = sum(
        ran[label(p)]["passed"] + ran[label(p)]["skipped"]
        for p in PACKAGES
        if p.parent.name == "projects"
    )
    assert int(stated.group(1).replace(",", "")) == total


#: `cd platform && python -m pytest -q   # 127 passed, 9 skipped` in an index README.
#: The package is named by the `cd`, so the line is checkable without guessing.
CD_QUOTED = re.compile(
    r"cd\s+([\w.-]+)\s*&&[^\n#]*pytest -q[^\n#]*#\s*(\d[\d,]*)\s+(tests?|passed)"
    r"(?:,\s*(\d+)\s+skipped)?",
)

INDEXES = sorted(
    readme
    for readme in (
        ROOT / "README.md",
        ROOT / "projects" / "README.md",
        ROOT / "products" / "README.md",
        ROOT / "apps" / "README.md",
    )
    if readme.is_file()
)


def test_the_indexes_quoting_a_per_package_count_are_found():
    """One index quotes them. Pinned, because a sweep over nothing passes.

    This is the gap that let `products/README.md` sit at "127 passed, 9 skipped"
    while `platform/README.md` was corrected to 143: the per-package counts in an
    index are the same class of claim, and the sweep above only reads each package's
    own README.
    """
    quoting = [i for i in INDEXES if CD_QUOTED.search(i.read_text(encoding="utf-8"))]
    assert [i.parent.name for i in quoting] == ["products"]


@pytest.mark.parametrize("index", INDEXES, ids=lambda p: f"{p.parent.name}/README.md")
def test_a_per_package_count_in_an_index_is_the_one_pytest_collects(index: Path):
    quoted = CD_QUOTED.findall(index.read_text(encoding="utf-8"))
    if not quoted:
        pytest.skip(f"{index.parent.name}/README.md quotes no per-package count")

    ran = recorded()
    for name, number, kind, skipped in quoted:
        package = index.parent / name
        assert package.is_dir(), f"{index}: `cd {name}` names no directory here"
        check(f"{index.parent.name}/README.md: {name}", number, kind, skipped, ran[label(package)])


# -- RUNNING.md, whose counts did not add up ------------------------------


RUNNING = ROOT / "RUNNING.md"


def test_running_md_counts_the_uis_that_exist():
    """It said nine, then three, then four - sixteen across eleven projects.

    All eleven ship a `ui/`; four carry a `package.json`. The sentence was a
    judgement about whether a browser adds anything, written as a count of what is
    there, under a line reading "Verified 2026-09-17. Every command below was run on
    this PC."
    """
    import re

    uis = sorted(p for p in (ROOT / "projects").glob("*/ui") if p.is_dir())
    npm = sorted(p for p in uis if (p / "package.json").exists())
    stdlib = len(uis) - len(npm)

    text = RUNNING.read_text(encoding="utf-8")
    words = {"seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "four": 4}
    stated = re.search(
        r"All (\w+) ship a `ui/`\.\s*(\w+) run from the standard library[^;]*;\s*(\w+) are",
        text,
    )
    assert stated, "the short answer no longer states the three counts"

    assert words[stated.group(1).lower()] == len(uis), f"{len(uis)} ui directories"
    assert words[stated.group(2).lower()] == stdlib, f"{stdlib} stdlib"
    assert words[stated.group(3).lower()] == len(npm), f"{len(npm)} with package.json"
    assert stdlib + len(npm) == len(uis), "the three numbers have to close"


def test_running_mds_test_everything_loop_names_real_directories():
    """It looped over bare names against `NN_name` directories, so the first `cd`
    failed and nothing ran."""
    import re

    text = RUNNING.read_text(encoding="utf-8")
    block = text[text.index("## Testing everything at once") :]
    block = block[: block.index("```", block.index("```bash") + 7)]

    assert "for r in repo-cartographer" not in block, "the bare-name loop is back"
    assert "for d in projects/*/" in block

    # And every path the block names exists.
    for path in re.findall(r"(?:python|uv run) (\S+\.py)", block):
        assert (ROOT / path).exists(), f"{path} is documented and missing"


def test_the_recorded_counts_still_match_collection():
    """The fixture is a measurement, so it goes stale. This is how far it can.

    Collection is cheap and the runner's `passed + skipped` must equal it, so a suite
    that gained or lost a test is caught here within one root-suite run. What this
    cannot see is a test that flipped from passing to skipping: the total holds and the
    split is stale, so a `passed` claim could be one too high until the next
    `--write-counts`. Narrow, and named rather than left to be discovered.
    """
    ran = recorded()
    assert sorted(ran) == sorted(label(p) for p in PACKAGES), (
        "the fixture does not cover the same 32 packages; "
        "run `python scripts/test_all.py --write-counts`"
    )
    stale = {
        name: (entry["passed"] + entry["skipped"], collected(ROOT / name))
        for name, entry in ran.items()
        if entry["passed"] + entry["skipped"] != collected(ROOT / name)
    }
    assert not stale, (
        f"recorded (passed+skipped) != collected for {stale}; "
        "run `python scripts/test_all.py --write-counts`"
    )


def test_the_recorded_counts_are_a_fresh_clones_and_not_this_machines():
    """The fixture has to be the numbers a reader reproduces.

    `REPOS_ROOT` defaults to the folder this checkout sits in. On a developer machine
    with a tree of checkouts beside it, `20_driftwatch` runs 18 tests a fresh clone
    skips and `01_revenue-desk` one more - so a sweep recorded here and pasted into the
    READMEs publishes a count true on exactly one computer. `scripts/test_all.py
    --write-counts` points those variables at an empty directory for that reason, and
    this asserts the fixture says it did.
    """
    # Imported by path: `scripts/` is not a package, and hard-coding the names here
    # would let the runner stop withholding one without this noticing.
    import importlib.util

    spec = importlib.util.spec_from_file_location("test_all", ROOT / "scripts" / "test_all.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    FRESH_ENV = runner.FRESH_ENV

    recorded = json.loads(COUNTS.read_text(encoding="utf-8"))
    assert recorded.get("fresh") == sorted(FRESH_ENV), (
        "the fixture does not record which inputs were withheld; re-run "
        "`python scripts/test_all.py --write-counts`"
    )
    # And the two suites that have an environment-dependent half must be recorded with
    # that half skipped, which is the whole point and the one thing an unset-rather-
    # than-emptied environment would silently get wrong.
    for name in ("products/20_driftwatch", "products/01_revenue-desk"):
        assert recorded["suites"][name]["skipped"] > 0, (
            f"{name} was recorded with nothing skipped, so the sweep saw a tree of "
            "checkouts it should not have"
        )
