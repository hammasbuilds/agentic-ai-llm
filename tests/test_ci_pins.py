"""The workflow against the project it builds: tool versions, and the sweep it runs.

CI has two jobs that lint the same tree. `platform` installs with `uv sync`, which
honours the dev group's `ruff>=0.16,<0.17`; `packages` ran `pip install pytest ruff`,
which honours nothing. `ruff format` output changes between minor versions, so the
failure that produces is a formatting diff in files nobody touched, in whichever job
resolved the newer version - and it arrives on an unrelated pull request.

The sweep had the same shape of problem. `python scripts/test_all.py` without `--fresh`
reads whatever the runner has: `REPOS_ROOT` defaults to the parent of the checkout,
which on a runner is not empty, and every count in every README is measured with
`--fresh`. CI was comparing a different run against them.

Both are checked here rather than in a comment, because a comment saying "keep these
equal" is the thing that was already there.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"


def test_the_workflow_exists_and_is_the_only_one():
    """A sweep over no workflows passes, and a second workflow would not be checked."""
    found = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert [p.name for p in found] == ["ci.yml"], found


def test_every_pip_installed_tool_is_pinned():
    """`pip install <name>` with no specifier is the defect. Each one named here has
    to carry a version range, whatever that range is."""
    text = WORKFLOW.read_text(encoding="utf-8")
    unpinned = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("- run: pip install", "run: pip install")):
            continue
        args = stripped.split("pip install", 1)[1]
        for token in re.findall(r'"[^"]+"|\S+', args):
            name = token.strip('"')
            if name.startswith("-"):
                continue
            if not re.search(r"[<>=!~]", name):
                unpinned.append(name)
    assert not unpinned, f"installed with no version: {unpinned}"


def test_the_two_jobs_pin_the_same_versions():
    """They lint and run the same files with the same config, so a different version
    of the tool is a different answer about the same tree."""
    declared = PYPROJECT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for tool in ("ruff", "pytest"):
        found = re.search(rf'"({tool}[<>=!~][^"]+)"', declared)
        assert found, f"the dev group no longer pins {tool}"
        spec = found.group(1).replace(" ", "")
        in_ci = {m.replace(" ", "") for m in re.findall(rf'"({tool}[<>=!~][^"]*)"', workflow)}
        assert in_ci, f"the packages job no longer pins {tool}"
        assert in_ci == {spec}, f"pyproject pins {spec}; the workflow pins {sorted(in_ci)}"


def test_the_sweep_runs_the_way_the_counts_were_measured():
    """`--write-counts` implies `--fresh` in the runner, and every recorded count was
    taken that way. CI running the sweep without it checks a different thing."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    sweeps = [
        line.strip()
        for line in workflow.splitlines()
        if "scripts/test_all.py" in line and line.strip().startswith(("run:", "- run:"))
    ]
    assert sweeps, "CI no longer runs the sweep"
    for line in sweeps:
        assert "--fresh" in line or "--write-counts" in line, line


def test_ci_lints_and_formats_every_tree_that_holds_python():
    """The two gaps this workflow's own comments record - `projects/` unlinted for 56
    errors, 70 files under `products/` unformatted - were both a missing path in a
    command. Asserted so a new top-level tree cannot repeat it."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    trees = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir()
        and not path.name.startswith((".", "_"))
        and any(path.rglob("*.py"))
        and path.name not in {"data", "docs"}
    }
    assert trees, "no python trees found"
    for check in ("ruff check", "ruff format --check"):
        covered = " ".join(line for line in workflow.splitlines() if check in line)
        missing = sorted(t for t in trees if t not in covered)
        assert not missing, f"{check} does not mention {missing}"
