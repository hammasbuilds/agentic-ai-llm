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
import os
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


def runner():
    """`scripts/test_all.py` loaded by path; it is a script, not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("test_all", ROOT / "scripts" / "test_all.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def skip_during_the_counting_sweep() -> None:
    """These tests compare the READMEs against the fixture that sweep is writing.

    So during the sweep they are checking the PREVIOUS fixture, which is the stale one
    by definition - and the cycle is otherwise unbreakable, because the runner refuses
    to write a fixture from a red sweep and the sweep is red because the fixture has
    not been written yet. The runner sets `AAL_COUNTING_SWEEP` for this one suite.
    """
    if os.environ.get(runner().SWEEP_MARKER):
        pytest.skip("inside `test_all.py --write-counts`, which is writing this fixture")


def recorded() -> dict[str, dict[str, int]]:
    """The fixture, or a skip if the run writing it is in progress.

    The skip lives here rather than in each caller. It was in two of the six tests that
    read this file, and the other four went red inside the sweep for the same reason -
    they were comparing against the fixture the sweep had not written yet. One place
    cannot be missed; six can.
    """
    skip_during_the_counting_sweep()
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


#: Python UI frameworks a `ui/` can be written against. Each is declared as that
#: package's own `ui` extra, so needing one is not "nothing to install".
UI_FRAMEWORKS = ("nicegui", "marimo", "panel", "reflex", "streamlit", "gradio", "dash")


def _ui_kinds() -> dict[str, list[str]]:
    """Each `projects/*/ui` by what it needs: npm, a Python framework, or nothing.

    Classified by what the directory CONTAINS - a `package.json`, or a Python file
    importing a framework - rather than by subtraction. The guard this replaces
    counted `package.json` and called everything else stdlib, which is how
    `02_test-smith` (nicegui), `08_csv-analyst` (marimo), `09_log-detective` (panel)
    and `11_study-tutor` (reflex) were counted as needing nothing, each of them
    listed in RUNNING.md's own table as `uv run --extra ui …`.
    """
    import re as _re

    kinds: dict[str, list[str]] = {"npm": [], "framework": [], "stdlib": []}
    for ui in sorted(p for p in (ROOT / "projects").glob("*/ui") if p.is_dir()):
        name = ui.parent.name
        if (ui / "package.json").exists():
            kinds["npm"].append(name)
            continue
        # A UI can also need a framework through the BROWSER, which no amount of reading
        # Python finds. `07_compliance-auditor` imported `lit@3.2.1` from
        # cdn.jsdelivr.net in its JavaScript and was classified `stdlib` - needing
        # nothing at all - in a project whose badge reads `runtime deps 0` and whose
        # README says "Installed: nothing". Looked for now, because "classified by what
        # the directory CONTAINS" has to mean all of what it contains.
        web = "\n".join(
            f.read_text(encoding="utf-8", errors="replace")
            for f in [*ui.rglob("*.js"), *ui.rglob("*.mjs"), *ui.rglob("*.html")]
        )
        if _re.search(r"""["'](?:https?:)?//[^"']*(?:cdn|unpkg|jsdelivr|esm\.sh)""", web):
            kinds["npm"].append(name)
            continue

        source = "\n".join(
            f.read_text(encoding="utf-8", errors="replace") for f in ui.rglob("*.py")
        )
        imported = [
            fw
            for fw in UI_FRAMEWORKS
            if _re.search(rf"^\s*(?:import|from)\s+{fw}\b", source, _re.MULTILINE)
        ]
        kinds["framework" if imported else "stdlib"].append(name)
    return kinds


def test_running_md_counts_the_uis_that_exist():
    """It said nine, then three, then four, then seven.

    Seven was "eleven minus the four with a `package.json`", and this test closed that
    arithmetic with `assert stdlib + len(npm) == len(uis)` - a restatement of the
    subtraction that produced the numbers, so it could not fail. The sentence it
    guarded put four projects that need a Python UI framework in the "nothing to
    install" column.

    Three counts, each measured independently, and no closing identity.
    """
    import re

    kinds = _ui_kinds()
    uis = sum(len(v) for v in kinds.values())
    assert uis == 11, kinds

    text = RUNNING.read_text(encoding="utf-8")
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
    }
    stated = re.search(
        r"All (\w+) ship a `ui/`\.\s*(\w+) run from the standard library[^;]*;\s*"
        r"(\w+) need `npm install`;\s*(\w+) need a Python UI framework",
        text,
    )
    assert stated, "the short answer no longer states the four counts"

    assert words[stated.group(1).lower()] == uis, kinds
    assert words[stated.group(2).lower()] == len(kinds["stdlib"]), kinds["stdlib"]
    assert words[stated.group(3).lower()] == len(kinds["npm"]), kinds["npm"]
    assert words[stated.group(4).lower()] == len(kinds["framework"]), kinds["framework"]


def test_every_framework_ui_declares_the_extra_it_needs():
    """A UI needing a framework is only honest if the package says how to get it.

    This is what makes "needs a Python UI framework" actionable rather than a label:
    each of the four is listed in RUNNING.md as `uv run --extra ui …`, so each has to
    have that extra.
    """
    kinds = _ui_kinds()
    assert kinds["framework"], kinds
    for name in kinds["framework"]:
        pyproject = (ROOT / "projects" / name / "pyproject.toml").read_text(encoding="utf-8")
        assert "[project.optional-dependencies]" in pyproject, name
        assert "ui" in pyproject, name
        assert "--extra ui" in RUNNING.read_text(encoding="utf-8"), name


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

    ran = dict(recorded())
    # `(root)` is in the fixture as information - whether the repository's own suite is
    # green in a fresh environment - and not as a published count: the sweep runs it
    # with the fixture-reading tests suppressed, so its passed/skipped are the in-sweep
    # figures. The root README's claim is checked by collection instead, below.
    root_entry = ran.pop(runner().ROOT_LABEL, None)
    assert root_entry is not None, (
        "the fixture has no root entry, so the repository's own suite is outside the "
        "sweep; run `python scripts/test_all.py --write-counts`"
    )
    assert root_entry["outcome"] == "ok", root_entry

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

    # Reads the file directly for its `fresh` key, so it needs the sweep guard that
    # `recorded()` carries for everything else.
    skip_during_the_counting_sweep()
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


#: Variables a suite may read without it changing whether anything runs: a tuning knob,
#: a colour setting, pytest's own. Each is here because it was looked at, not because it
#: was unrecognised.
NOT_GATING = {
    "TERM",
    "PY_COLORS",
    "NO_COLOR",
    "FORCE_COLOR",
    "HOME",
    "PATH",
    "TMPDIR",
    "PYTEST_CURRENT_TEST",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_DEBUG_TEMPROOT",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    # Timeouts and retry windows. They change how long a probe waits, never whether a
    # test is collected.
    "OLLAMA_RETRY_AFTER",
    "OLLAMA_PROBE_TIMEOUT",
    "OLLAMA_TAGS_TTL",
    "REDIS_CONNECT_TIMEOUT",
    "REDIS_OP_TIMEOUT",
    "REDIS_RETRY_AFTER",
    "BUS_RETRY_AFTER",
    "BUS_START_TIMEOUT",
    "GEN_CONCURRENCY",
    "MODEL",
}


def test_the_withheld_list_is_checked_against_the_tree_not_against_itself():
    """The reason the `CSV_CORPUS` leak survived.

    The test above compares `recorded["fresh"]` with `FRESH_ENV` - the runner's own
    list - so a list missing a variable certifies itself and the fixture agrees. It
    stayed green while `08_csv-analyst` read a sibling checkout through all of it.

    This reads the variables out of the tree instead: every `os.environ.get("NAME")` in
    a `tests/` or `src/` file under `projects/` or `products/` either withholds in
    `FRESH_ENV` or is named in `NOT_GATING` with a reason. A new data-gated suite then
    fails here on the day it is added, which is the only moment anyone is looking.
    """
    import importlib.util
    import re

    spec = importlib.util.spec_from_file_location("test_all", ROOT / "scripts" / "test_all.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    read: dict[str, list[str]] = {}
    for tree in ("projects", "products"):
        for path in (ROOT / tree).rglob("*.py"):
            parts = set(path.parts)
            if "__pycache__" in parts or ".venv" in parts or "site-packages" in parts:
                continue
            for name in re.findall(
                r'os\.environ(?:\.get)?\(\s*"([A-Z][A-Z0-9_]*)"',
                path.read_text(encoding="utf-8", errors="replace"),
            ):
                read.setdefault(name, []).append(str(path.relative_to(ROOT)))

    assert read, "no environment reads found at all, so this test is checking nothing"
    # The sweep's own marker is accounted for here rather than in NOT_GATING, because
    # it DOES gate - it suppresses 47 tests, which `pytest -rs` names on one line -
    # beside the list it is an exception to.
    unaccounted = sorted(set(read) - set(runner.FRESH_ENV) - NOT_GATING - {runner.SWEEP_MARKER})
    assert not unaccounted, (
        "these variables are read by a suite and are neither withheld by the fresh "
        "sweep nor listed as non-gating: "
        + "; ".join(f"{name} ({', '.join(sorted(set(read[name]))[:2])})" for name in unaccounted)
    )


def test_every_withheld_variable_is_one_something_actually_reads():
    """The other direction. A list that withholds variables nothing reads looks
    thorough and proves nothing, and it is how a renamed variable goes unnoticed: the
    old name sits in the tuple, the new one gates freely."""
    import importlib.util
    import re

    spec = importlib.util.spec_from_file_location("test_all", ROOT / "scripts" / "test_all.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    everywhere = ""
    for tree in ("projects", "products", "apps", "tests"):
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts or "site-packages" in path.parts:
                continue
            everywhere += path.read_text(encoding="utf-8", errors="replace")

    orphans = [name for name in runner.FRESH_ENV if not re.search(rf'"{name}"', everywhere)]
    assert not orphans, f"withheld but read nowhere: {orphans}"


# -- the badge at the top of the page, which nothing read at all --------------------
#
# This module opens "Every test count quoted in a README, against what pytest
# collects." `QUOTED` requires the literal `pytest -q … #`, so the shields.io badge in
# the header - the most-read count in the file, and the first thing on the page - was
# outside every check here. Five of the ten were wrong when this was written:
# cartographer 39 against 42, review-bot 43 against 46, release-captain 50 against
# 49 + 1 skipped, csv-analyst 47 against 56, log-detective 39 against 46.
#
# Checked against the recorded fixture rather than by collection, because the badge
# states a pass/skip split and collection cannot tell one from the other - the same
# reason the `pytest -q` check above uses the fixture.

BADGE = re.compile(r"img\.shields\.io/badge/tests-([^-\s\"']+)-")


def _badge_claim(package: Path) -> tuple[int, int] | None:
    """The pass and skip counts a README's badge states, or None if it has none."""
    found = BADGE.search((package / "README.md").read_text(encoding="utf-8"))
    if not found:
        return None
    text = found.group(1).replace("%20", " ").replace("%2B", "+")
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if "skipped" in text:
        return (numbers[0], numbers[1]) if len(numbers) >= 2 else None
    return (numbers[0], 0) if numbers else None


BADGED = [p for p in PACKAGES if _badge_claim(p) is not None]


def test_the_badges_are_still_there_to_check():
    """A sweep over an empty list passes, and ten of these READMEs carry one."""
    assert len(BADGED) >= 10, [p.name for p in BADGED]


@pytest.mark.parametrize("package", BADGED, ids=[p.name for p in BADGED])
def test_each_readme_badge_is_what_the_suite_really_did(package: Path):
    claimed = _badge_claim(package)
    key = f"{package.parent.name}/{package.name}"
    row = recorded().get(key)
    if row is None:
        pytest.skip(f"no recorded count for {key}")
    assert claimed == (row["passed"], row["skipped"]), (
        f"{key}: the badge says {claimed[0]} passed and {claimed[1]} skipped; "
        f"the suite does {row['passed']} and {row['skipped']}"
    )


@pytest.mark.parametrize("package", BADGED, ids=[p.name for p in BADGED])
def test_a_badge_and_the_command_beside_it_do_not_contradict_each_other(package: Path):
    """Two counts on one page, which is two places for one of them to be wrong - and
    was: every one of the five drifted badges sat above a corrected `pytest -q` line."""
    text = (package / "README.md").read_text(encoding="utf-8")
    quoted = QUOTED.search(text)
    if not quoted:
        pytest.skip("no `pytest -q` line to compare against")
    passed, skipped = _badge_claim(package)
    stated = int(quoted.group(1).replace(",", ""))
    if quoted.group(2) == "passed":
        assert stated == passed, (package.name, stated, passed)
        assert int(quoted.group(3) or 0) == skipped, (package.name, quoted.group(3), skipped)
    else:
        assert stated == passed + skipped, (package.name, stated, passed + skipped)


# -- the per-file counts, which this module's own regex did not match ----------

#: A count beside a command that names ONE test file: `pytest tests/test_real_x.py -q
#: # 17 passed`. `QUOTED` above requires the literal "pytest -q", so every one of these
#: was invisible to the module whose job is catching a drifted count - twenty-one
#: claims across nineteen READMEs, checked by nothing.
#:
#: Six of them were wrong when this test was written: revenue-desk 17 against 18,
#: bid-desk 9 against 11, watchtower 15 against 16, swarm-lab 10 against 12,
#: graph-clinic 11 against 12, driftwatch 17 against 20. Every one was a test added to
#: the file by work that had no reason to reread the README beside it, which is the
#: same failure the module already catches one line higher up and could not see here.
PER_FILE = re.compile(
    r"python -m pytest (tests/[\w./]+\.py) -q\s*#\s*(\d+)\s+passed(?:,\s*(\d+)\s+skipped)?"
)


def _per_file_claims() -> list[tuple[Path, str, int]]:
    claims = []
    for package in PACKAGES:
        text = (package / "README.md").read_text(encoding="utf-8")
        for m in PER_FILE.finditer(text):
            claims.append((package, m.group(1), int(m.group(2)) + int(m.group(3) or 0)))
    return claims


PER_FILE_CLAIMS = _per_file_claims()


def test_the_per_file_claims_are_still_there_to_check():
    """A sweep over an empty list passes. These were found by reading the READMEs, so
    if the convention changes this says so rather than going quiet."""
    assert len(PER_FILE_CLAIMS) >= 20, len(PER_FILE_CLAIMS)
    assert len({package.name for package, _, _ in PER_FILE_CLAIMS}) >= 19


@pytest.mark.parametrize(
    "package,rel,stated",
    PER_FILE_CLAIMS,
    ids=[f"{package.name}/{rel.split('/')[-1]}" for package, rel, _ in PER_FILE_CLAIMS],
)
def test_each_per_file_count_is_the_one_pytest_collects(package: Path, rel: str, stated: int):
    """Collection, which cannot drift, against the sum the README promises.

    Compared against collected total rather than passes, because collection cannot tell
    a pass from a skip - so a README quoting "31 passed, 1 skipped" is checked as 32.
    Two of these files have no skips to split and the rest state none, so the sum is
    the whole claim either way.
    """
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", rel],
        cwd=str(package),
        capture_output=True,
        text=True,
        timeout=600,
    )
    found = re.search(r"(\d+) tests? collected", done.stdout)
    assert found, done.stdout[-500:]
    assert int(found.group(1)) == stated, (
        f"{package.name}/{rel} says {stated}; pytest collects {found.group(1)}"
    )


# -- the repository's own suite, which was not swept at all -------------------


def test_the_root_readme_states_the_number_this_suite_collects():
    """The blind spot at the front door, closed the only way it can be.

    `PACKAGES` above is every directory under `projects/` and `products/` with a
    `tests/`, so the root suite - the one a reader runs first - was the one suite whose
    published count nothing compared to anything. `README.md` said "317 passed, 38
    skipped" against a suite already collecting more than twice that, through every
    round of correcting the sub-packages' counts.

    The figure is deliberately not restated here. This docstring used to give the
    correction as "606 / 38: wrong by 329" while the README gave it as "wrong by 348"
    and referred to a third number entirely - four figures for one count, in the two
    places whose subject is counts that drift when nobody rereads the prose. The
    assertion below reads the README and asks pytest; neither number is written down
    twice.

    Checked by COLLECTION, not against the recorded fixture. A suite cannot assert its
    own pass and skip counts without running itself, and the sweep that records them
    runs this suite with the fixture-reading tests suppressed - so the recorded entry is
    the in-sweep count, not a reader's. Collection has no such cycle, and it catches the
    thing that actually drifts: a test added or removed.
    """
    import re

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    stated = re.search(r"\*\*(\d[\d,]*) tests collected\*\*", readme)
    assert stated, "the root README no longer states what the suite collects"
    assert int(stated.group(1).replace(",", "")) == collected(ROOT), (
        f"README.md says {stated.group(1)} tests collected; pytest collects {collected(ROOT)}"
    )


def test_the_root_suite_is_in_the_sweep_not_just_in_the_fixture():
    """A fixture entry nothing regenerates goes stale the moment a test is added."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("test_all", ROOT / "scripts" / "test_all.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    swept = runner.suites(runner.TREES)
    assert ROOT in swept, "scripts/test_all.py does not sweep the repository's own suite"
    # And a single-tree sweep does not, because `--write-counts` refuses a partial tree
    # anyway and running the root suite inside `test_all.py projects` would be surprising.
    assert ROOT not in runner.suites(("projects",))


def test_no_suite_reads_a_home_directory_path_the_sweep_cannot_withhold():
    """The leak the variable check above is blind to.

    `test_the_withheld_list_is_checked_against_the_tree_not_against_itself` finds every
    `os.environ.get("NAME")` in the two trees and insists the sweep withholds it. A
    module that hardcodes a path reads no variable at all, so it is invisible:
    `14_graph-clinic` had `CACHE = Path.home() / ".cache/huggingface/datasets/..."` as a
    module constant and ran all 28 of its tests inside a sweep that had pointed
    `HF_HOME` at an empty directory. On a fresh clone 17 run and 11 skip.

    `Path.home()` inside a function that consults the environment first is fine - that
    is the documented default. The check is per FUNCTION, not per file: a file-wide
    exemption let the corrupted version through, because the file still contained the
    resolver that reads `HF_HOME` while the constant beside it reached for home
    directly. Module-level use is refused outright, since there is no earlier branch it
    can be the fallback of.
    """
    import ast

    def reaches_home(nodes) -> bool:
        """`Path.home()` called anywhere in these statements.

        Matched as a CALL to an attribute named `home`, not as the string "home"
        anywhere in the dump - the first version did the latter and flagged
        `DOMAIN = "home"` in a product that has nothing to do with filesystem paths.
        """
        for statement in nodes:
            for node in ast.walk(statement):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "home"
                ):
                    return True
        return False

    def reads_environment(nodes) -> bool:
        """`os.environ`, `os.getenv`, or pytest's `monkeypatch.setenv`/`delenv`.

        The monkeypatch forms count: a test that sets and unsets a variable and then
        asserts the fallback is consulting the environment, and is the test that keeps
        the fallback honest. Without them, the one test asserting what the default IS
        was flagged by the check that exists because of it.
        """
        for statement in nodes:
            for node in ast.walk(statement):
                if isinstance(node, ast.Attribute) and node.attr in (
                    "environ",
                    "getenv",
                    "setenv",
                    "delenv",
                ):
                    return True
                if isinstance(node, ast.Name) and node.id in ("environ", "getenv"):
                    return True
        return False

    allowed = {
        # The resolver itself: the default branch, after both overrides.
        "apps/_engine/hf_cache.py",
        # Asserts what that default IS, so it has to name it.
        "tests/test_hermetic.py",
        # A form's initial value in a notebook UI, not a data path a test reads.
        "projects/08_csv-analyst/ui/notebook.py",
        # A test asserting the string is absent from another file.
        "projects/02_test-smith/tests/test_runner.py",
    }
    offenders: list[str] = []
    for tree in ("projects", "products", "apps", "scripts", "tests"):
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or "site-packages" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in allowed:
                continue
            try:
                parsed = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue

            for node in ast.walk(parsed):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    continue
                # This scope's own statements. A nested function is walked separately,
                # so a parent is not held responsible for what one of its children does.
                own = [
                    n
                    for n in node.body
                    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if not reaches_home(own) or reads_environment(own):
                    continue
                offenders.append(f"{rel}:{getattr(node, 'name', '<module level>')}")

    assert not offenders, (
        "these reach for the home directory without consulting the environment in the "
        f"same scope, so `test_all.py --fresh` cannot withhold it: {offenders}"
    )


def test_the_projects_index_fresh_split_adds_up_to_its_own_total():
    """`projects/README.md` states two totals, and only one was ever checked.

    "**591 tests across the eleven**" had a test; "On a fresh clone **477 run and 25
    skip**" had none, and 477 + 25 is 502. The two sat four paragraphs apart for long
    enough that the second was wrong by 89 tests while the first was right.

    A split that does not sum to the total it splits is the cheapest possible check and
    the one nobody wrote.
    """
    index = (ROOT / "projects" / "README.md").read_text(encoding="utf-8")
    total = re.search(r"\*\*(\d[\d,]*) tests across the eleven\*\*", index)
    split = re.search(r"On a fresh clone \*\*(\d+) run and (\d+) skip\*\*", index)
    assert total and split, "one of the two totals is gone; this test moved"

    stated = int(total.group(1).replace(",", ""))
    ran, skipped = int(split.group(1)), int(split.group(2))
    assert ran + skipped == stated, (
        f"the index says {stated} tests across the eleven and {ran} run + "
        f"{skipped} skip, which is {ran + skipped}"
    )

    recorded_counts = recorded()
    measured_ran = sum(
        recorded_counts[label(p)]["passed"] for p in PACKAGES if p.parent.name == "projects"
    )
    measured_skipped = sum(
        recorded_counts[label(p)]["skipped"] for p in PACKAGES if p.parent.name == "projects"
    )
    assert (ran, skipped) == (measured_ran, measured_skipped), (
        f"the index says {ran} run and {skipped} skip; the sweep recorded "
        f"{measured_ran} and {measured_skipped}"
    )


def test_the_skip_breakdown_names_every_skip_the_projects_tree_has():
    """The prose enumerates them - "thirteen tests, two, one and nine" - and that is a
    claim about the same 25."""
    index = (ROOT / "projects" / "README.md").read_text(encoding="utf-8")
    split = re.search(r"On a fresh clone \*\*\d+ run and (\d+) skip\*\*", index)
    assert split
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    }
    named = re.findall(
        r"has (\w+) tests?|`compliance-auditor` (\w+)|`release-captain` (\w+)|"
        r"`csv-analyst` (\w+)",
        index,
    )
    counted = sum(words[w] for group in named for w in group if w in words)
    assert counted == int(split.group(1)), (
        f"the prose names {counted} skipped tests and the figure says {split.group(1)}"
    )


def test_the_counting_marker_suppresses_the_number_the_runner_says_it_does():
    """`AAL_COUNTING_SWEEP` was documented as suppressing "three tests and nothing else".

    It suppresses 47: `recorded()` is read by tests parametrised across all 33 packages,
    so one skip in one helper becomes 47 in the run. That sentence is why the root
    suite's two published split figures were labelled with the wrong cause - the README
    called the marker run "a fresh clone, the figure a reader reproduces", when the fresh
    data paths change nothing in this suite and the marker changes 47 of its 1,298.

    Counted by collecting, not by running, so this stays fast: every test whose body
    reaches `recorded()` or `_skip_during_the_sweep()` is one of them. Asserted against
    the number the runner's own comment states, so the two cannot drift apart again.
    """
    import ast

    source = (ROOT / "tests" / "test_documented_counts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    #: Helpers whose call means "this test reads the fixture", so the marker skips it.
    gated_helpers = {"recorded"}
    gated: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        if calls & gated_helpers:
            gated.append(node.name)

    assert gated, "no test reads the fixture any more; this module changed shape"

    # Parametrised tests contribute one skip per case, so the test count is not the
    # skip count - which is the whole reason "three" was wrong.
    stated = re.search(r"It suppresses \*\*(\d+)\*\* tests", (ROOT / "scripts" / "test_all.py").read_text(encoding="utf-8"))
    assert stated, "scripts/test_all.py no longer states a suppression count"
    assert int(stated.group(1)) == 47, (
        f"scripts/test_all.py says {stated.group(1)}; the measured figure is 47 "
        "(`AAL_COUNTING_SWEEP=1 pytest tests/ -q -rs`). Re-measure, do not adjust."
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**47** tests" in readme, "the README no longer states the suppression count"
