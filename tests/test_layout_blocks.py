"""The Layout block names every test file and the number of tests in it.

`tests/test_documented_counts.py` is the module about count drift, and it recognises a
quoted count only in the literal form `pytest -q ... # N tests`. Every project README
also carries a Layout block that names its test files and their counts in prose, and
that block sat outside every check in the repository: an independent reviewer found
**eleven** stale counts across ten projects, wrong by 3 to 19 tests, and six projects
whose block listed some of `tests/` and not the rest.

A block that reads as the contents of a directory and is a choice of two files from four
is worse than no block: a reader adding up the counts gets a number nobody intended, and
`test_operations.py` saying 21 where it collects 40 is the drift this repository has a
module about.

Counted from `pytest --collect-only`, per file, which is the only form of this claim that
can be checked.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"

#: A Layout line for a test file, in either form the blocks use: bare under a `tests/`
#: heading, or `tests/`-prefixed where there is no heading.
_LINE = re.compile(
    r"^[ ]*(?:tests/)?(test_[a-z_0-9]+\.py)[ ]+(\d+)[ ]+tests?\b",
    re.M,
)


def _projects() -> list[str]:
    return sorted(
        d.name
        for d in PROJECTS.iterdir()
        if d.is_dir()
        and (d / "README.md").is_file()
        and (d / "tests").is_dir()
        and _LINE.search((d / "README.md").read_text(encoding="utf-8"))
    )


def _collected(directory: Path) -> dict[str, int]:
    """Tests collected per file, from pytest.

    `--collect-only -q` prints one `path::test` line each, which is the only place this
    number exists: a suite cannot count itself without running, and a figure typed into
    a README has nothing behind it.
    """
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(directory), "-q", "--collect-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-1000:]
    counts: dict[str, int] = {}
    for line in done.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        name = Path(line.split("::", 1)[0]).name
        counts[name] = counts.get(name, 0) + 1
    assert counts, f"nothing collected under {directory}"
    return counts


def _quoted(project: str) -> dict[str, int]:
    text = (PROJECTS / project / "README.md").read_text(encoding="utf-8")
    return {name: int(count) for name, count in _LINE.findall(text)}


def test_there_are_layout_blocks_to_check():
    """The sweep below is parametrised over what this finds, so an empty result would
    be a silent pass over the whole repository - which is how the counts drifted."""
    found = _projects()
    assert len(found) >= 9, found


@pytest.mark.parametrize("project", _projects())
def test_every_count_in_a_layout_block_is_the_count_collected(project: str):
    quoted = _quoted(project)
    real = _collected(PROJECTS / project / "tests")
    wrong = {
        name: (stated, real.get(name))
        for name, stated in quoted.items()
        if real.get(name) != stated
    }
    assert wrong == {}, (
        f"projects/{project}/README.md states counts that are not the counts collected "
        f"(file: stated -> actual): {wrong}"
    )


@pytest.mark.parametrize("project", _projects())
def test_a_layout_block_names_every_test_file(project: str):
    quoted = set(_quoted(project))
    real = set(_collected(PROJECTS / project / "tests"))
    assert real - quoted == set(), (
        f"projects/{project}/README.md's Layout block omits {sorted(real - quoted)}. "
        "A block that lists most of a directory reads as an inventory and is a "
        "selection."
    )
    assert quoted - real == set(), (
        f"projects/{project}/README.md names {sorted(quoted - real)}, which collects "
        "nothing - a renamed or deleted file."
    )


def test_the_quoted_form_this_module_reads_is_not_the_one_the_other_module_reads():
    """Why this file exists rather than an addition to `test_documented_counts.py`.

    That module requires the literal `pytest -q ... #`, which is the whole-suite total
    at the top of a README. The Layout block is per file and in prose, and the two
    forms do not overlap - so neither module would have found the other's figures.
    """
    from tests import test_documented_counts as other

    pattern = getattr(other, "QUOTED", None)
    assert pattern is not None, "test_documented_counts.QUOTED moved; update this note"
    sample = "    test_parse.py   26 tests"
    assert _LINE.search(sample), sample
    assert not re.search(pattern if isinstance(pattern, str) else pattern.pattern, sample), (
        "the other module now reads the Layout form too, so this file is redundant"
    )
