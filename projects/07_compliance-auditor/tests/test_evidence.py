"""Collector tests. Collectors report facts; they must never decide anything."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from auditor.evidence import _top_level_imports, collect


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    write(
        root,
        "pyproject.toml",
        """
        [project]
        name = "demo"
        dependencies = ["httpx>=0.27", "rich"]
        [project.optional-dependencies]
        ui = ["nicegui>=2.0"]
    """,
    )
    write(root, "README.md", "# demo\n\n## What it does NOT do\n\nnothing\n")
    write(root, "src/demo/core.py", "import httpx\nfrom rich import print\n")
    write(root, "tests/test_core.py", "def test_x():\n    assert True\n")
    return root


# -- import extraction ---------------------------------------------------


def test_consecutive_imports_do_not_bleed_into_each_other():
    """The regex this replaced consumed following lines.

    `import\\s+([\\w.,\\s]+)` has `\\s` inside the class, so `import json`
    matched across newlines and reported `sys` and `from` as imports. It took
    the imports-declared control to a meaningless 0% across 30 repositories.
    """
    found = _top_level_imports("import json\nimport sys\nfrom pathlib import Path\n")
    assert found == {"json", "sys", "pathlib"}


def test_imported_names_are_not_mistaken_for_modules():
    assert _top_level_imports("from pydantic import Field, BaseModel") == {"pydantic"}


def test_dotted_imports_reduce_to_the_top_level():
    assert _top_level_imports("import os.path\nfrom a.b.c import d") == {"os", "a"}


def test_relative_imports_are_not_dependencies():
    assert _top_level_imports("from . import x\nfrom .sibling import y") == set()


def test_multiline_parenthesised_imports_are_read():
    found = _top_level_imports("from fastapi import (\n    FastAPI,\n    Request,\n)\n")
    assert found == {"fastapi"}


def test_an_unparseable_file_is_recorded_rather_than_contributing_nothing():
    """It used to return an empty set, which is indistinguishable from a file with
    no imports - so a repository whose only Python file does not parse looked exactly
    like one that imports nothing, and both import controls returned PASS on it.

    The audit still does not fail: the repository being audited is not required to
    be valid Python. The collector says it could not read the file, and the controls
    over imports decline rather than clear it.
    """
    from auditor.evidence import _UnparsedError

    with pytest.raises(_UnparsedError):
        _top_level_imports("def f(:" + chr(10))


def test_aliased_imports_use_the_module_not_the_alias():
    assert _top_level_imports("import numpy as np") == {"numpy"}


# -- collection ----------------------------------------------------------


def test_declared_dependencies_include_optional_groups(repo: Path):
    ev = collect(repo)
    assert ev.declared_dependencies == ["httpx>=0.27", "rich"]
    assert ev.declared_optional == {"ui": ["nicegui>=2.0"]}


def test_tests_are_separated_from_source(repo: Path):
    ev = collect(repo)
    assert ev.test_files == ["tests/test_core.py"]
    assert "src/demo/core.py" in ev.source_files


def test_src_layout_package_is_recognised_as_local(repo: Path):
    """With a src/ layout the first path element is `src`, not the package.

    Taking the first element flagged every repo's own package as an
    undeclared third-party import.
    """
    ev = collect(repo)
    assert "demo" in ev.local_packages
    assert "src" not in ev.local_packages


def test_readme_headings_are_captured(repo: Path):
    assert "What it does NOT do" in collect(repo).headings


def test_caches_and_venvs_are_not_scanned(repo: Path):
    write(repo, ".venv/lib/thing.py", "import evil\n")
    write(repo, "__pycache__/x.py", "import alsoevil\n")
    ev = collect(repo)
    assert "evil" not in ev.imported_modules
    assert "alsoevil" not in ev.imported_modules


def test_a_missing_directory_is_reported_not_raised(tmp_path: Path):
    ev = collect(tmp_path / "nope")
    assert ev.exists is False


def test_a_repo_without_pyproject_collects_cleanly(tmp_path: Path):
    write(tmp_path, "a.py", "import os\n")
    ev = collect(tmp_path)
    assert ev.pyproject_path is None
    assert ev.declared_dependencies == []


# -- git facts -----------------------------------------------------------


def test_git_state_is_observed(repo: Path):
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    ev = collect(repo)
    assert ev.has_git is True
    assert ev.has_remote is False  # nothing was added


def test_a_plain_folder_is_not_a_git_repo(repo: Path):
    ev = collect(repo)
    assert ev.has_git is False
    assert ev.tracked_junk == []
