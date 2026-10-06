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


def test_every_package_with_a_readme_is_swept():
    """A sweep over an empty list passes. Eleven tools, twenty products, the platform."""
    assert len(PACKAGES) == 32, [p.name for p in PACKAGES]


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

    actual = collected(package)
    for number, kind, skipped in quoted:
        stated = int(number.replace(",", "")) + (int(skipped) if skipped else 0)
        assert stated == actual, (
            f"{package.name}: README says {number} {kind}"
            + (f" and {skipped} skipped" if skipped else "")
            + f", which is {stated}; pytest collects {actual}"
        )


def test_the_projects_index_totals_the_eleven():
    """`projects/README.md` quotes a total across the tree, which drifts eleven ways."""
    index = (ROOT / "projects" / "README.md").read_text(encoding="utf-8")
    stated = re.search(r"\*\*(\d[\d,]*) tests across the eleven\*\*", index)
    assert stated, "the index no longer states a total"
    total = sum(collected(p) for p in PACKAGES if p.parent.name == "projects")
    assert int(stated.group(1).replace(",", "")) == total
