"""Control tests, and the property that makes the audit worth reading:
a control may only pass when something was actually observed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from auditor.controls import (
    CONTROLS,
    FAIL,
    INCONCLUSIVE,
    NOT_APPLICABLE,
    PASS,
    declared_deps_are_used,
    imports_are_declared,
    readme_limits,
    run_all,
)
from auditor.evidence import Evidence, collect
from auditor.report import Audit, RepoAudit, audit_folder


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def make(tmp_path: Path, name: str = "demo", **files: str) -> Evidence:
    root = tmp_path / name
    for rel, body in files.items():
        write(root, rel.replace("__", "/"), body)
    return collect(root)


# -- no inferred compliance ----------------------------------------------


def test_a_missing_readme_is_inconclusive_not_a_pass(tmp_path: Path):
    """Nothing was observed, so nothing may be asserted."""
    ev = make(tmp_path, **{"a.py": "x = 1\n"})
    assert readme_limits(ev).status == INCONCLUSIVE


def test_a_missing_pyproject_makes_dependency_controls_not_applicable(tmp_path: Path):
    ev = make(tmp_path, **{"a.py": "import httpx\n"})
    assert declared_deps_are_used(ev).status == NOT_APPLICABLE
    assert imports_are_declared(ev).status == NOT_APPLICABLE


def test_no_control_ever_passes_on_a_missing_directory(tmp_path: Path):
    ev = collect(tmp_path / "nope")
    statuses = {r.status for r in run_all(ev)}
    assert PASS not in statuses


def test_every_control_returns_a_detail(tmp_path: Path):
    ev = make(tmp_path, **{"a.py": "x = 1\n"})
    for result in run_all(ev):
        assert result.detail, f"{result.control} returned no detail"


def test_every_declared_control_is_run(tmp_path: Path):
    ev = make(tmp_path, **{"a.py": "x = 1\n"})
    assert {r.control for r in run_all(ev)} == {c.id for c in CONTROLS}


# -- dependency controls -------------------------------------------------


PYPROJECT = """
[project]
name = "demo"
dependencies = [{deps}]
"""


def test_an_unused_declared_dependency_fails(tmp_path: Path):
    ev = make(
        tmp_path,
        **{
            "pyproject.toml": PYPROJECT.format(deps='"httpx", "rich"'),
            "src__demo__a.py": "import httpx\n",
        },
    )
    result = declared_deps_are_used(ev)
    assert result.status == FAIL
    assert "rich" in result.detail


def test_an_undeclared_import_fails(tmp_path: Path):
    ev = make(
        tmp_path,
        **{
            "pyproject.toml": PYPROJECT.format(deps='"httpx"'),
            "src__demo__a.py": "import httpx\nimport streamlit\n",
        },
    )
    result = imports_are_declared(ev)
    assert result.status == FAIL
    assert "streamlit" in result.detail


def test_the_repos_own_package_is_not_an_undeclared_import(tmp_path: Path):
    ev = make(
        tmp_path,
        **{
            "pyproject.toml": PYPROJECT.format(deps=""),
            "src__demo__a.py": "def f(): pass\n",
            "src__demo__b.py": "from demo.a import f\n",
        },
    )
    assert imports_are_declared(ev).status == PASS


@pytest.mark.parametrize(
    ("module", "declared"),
    [
        ("cv2", "opencv-python-headless"),
        ("cv2", "opencv-python"),
        ("skimage", "scikit-image"),
        ("sklearn", "scikit-learn"),
        ("yaml", "PyYAML"),
        ("psycopg_pool", "psycopg"),
    ],
)
def test_distribution_aliases_are_understood(tmp_path: Path, module: str, declared: str):
    """`cv2` comes from several distributions; any of them satisfies the import."""
    ev = make(
        tmp_path,
        name=f"demo_{module}_{declared}".replace("-", "_"),
        **{
            "pyproject.toml": PYPROJECT.format(deps=f'"{declared}"'),
            "src__demo__a.py": f"import {module}\n",
        },
    )
    assert imports_are_declared(ev).status == PASS


def test_the_standard_library_is_never_an_undeclared_import(tmp_path: Path):
    """A hand-written stdlib list scored this control 0% across 30 repos."""
    ev = make(
        tmp_path,
        **{
            "pyproject.toml": PYPROJECT.format(deps=""),
            "src__demo__a.py": (
                "import tomllib\nimport graphlib\nimport zoneinfo\n"
                "import dataclasses\nimport statistics\n"
            ),
        },
    )
    assert imports_are_declared(ev).status == PASS


# -- the rate cannot be inflated -----------------------------------------


def test_inconclusive_results_are_excluded_from_the_rate():
    """Counting unmeasured controls as passes is how an audit reports 90%
    having measured a third of what it claimed."""
    from auditor.controls import Result

    repo = RepoAudit(
        "x",
        [
            Result("a", PASS, "d"),
            Result("b", FAIL, "d"),
            Result("c", INCONCLUSIVE, "d"),
            Result("d", NOT_APPLICABLE, "d"),
        ],
    )
    assert len(repo.counted) == 2
    assert repo.rate == 0.5


def test_an_empty_audit_reports_zero_not_one():
    assert Audit().rate == 0.0


def test_folder_audit_skips_non_projects(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    write(tmp_path, "real/README.md", "# real\n\n" + "word " * 60)
    audit = audit_folder(tmp_path)
    assert [r.name for r in audit.repos] == ["real"]


def test_an_import_control_does_not_clear_a_repository_it_could_not_read(tmp_path: Path):
    """The README's rule: "A control may return PASS only when a collector actually
    observed something."

    `_top_level_imports` returned an empty set on a SyntaxError and the walk skipped an
    unreadable file, both in silence — so a repository whose only Python file does not
    parse was indistinguishable from one that imports nothing, and both import controls
    returned [ok] on it. These two are 2 of the 10 rates behind the headline number.
    """
    (tmp_path / "only.py").write_text("import requests\ndef broken(:\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["requests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")

    evidence = collect(tmp_path)
    assert evidence.python_files == ["only.py"]
    assert evidence.imported_modules == set()
    assert evidence.unreadable_files == ["only.py"]

    by_id = {c.id: c.check(evidence) for c in CONTROLS}
    for control_id in ("deps-used", "imports-declared"):
        assert by_id[control_id].status == NOT_APPLICABLE, by_id[control_id]
        assert "could not be read" in by_id[control_id].detail


def test_a_repository_it_could_read_is_still_judged(tmp_path: Path):
    """The guard must not decline everything: a file that parses is still checked."""
    (tmp_path / "only.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["requests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")

    evidence = collect(tmp_path)
    assert evidence.unreadable_files == []
    by_id = {c.id: c.check(evidence) for c in CONTROLS}
    assert by_id["deps-used"].status != NOT_APPLICABLE


def test_a_pass_over_a_partly_read_repository_says_what_it_did_not_read():
    """A clean verdict over 99 of 100 files is not the same claim as over 100 of 100.

    The whole-repository case is declined outright, but a single unparseable file
    among many still produced a bare "every third-party import is declared" - and an
    undeclared import could be sitting in exactly the file that was not read.
    """
    ev = Evidence(
        name="r",
        root=Path("r"),
        pyproject_path="pyproject.toml",
        declared_dependencies=["requests"],
        python_files=["a.py", "b.py", "broken.py"],
        imported_modules={"requests"},
        unreadable_files=["broken.py"],
    )

    for control in (declared_deps_are_used, imports_are_declared):
        result = control(ev)
        assert result.status == PASS
        assert "1 of 3 Python file(s) could not be read" in result.detail


def test_a_pass_over_a_fully_read_repository_carries_no_caveat():
    ev = Evidence(
        name="r",
        root=Path("r"),
        pyproject_path="pyproject.toml",
        declared_dependencies=["requests"],
        python_files=["a.py"],
        imported_modules={"requests"},
    )
    for control in (declared_deps_are_used, imports_are_declared):
        result = control(ev)
        assert result.status == PASS
        assert "could not be read" not in result.detail
