"""Collect evidence from a repository. Nothing here decides anything.

The split matters: collectors gather facts, controls judge them. A collector
that returned "compliant" would be deciding policy at the point of
measurement, and the two would be impossible to argue with separately.

Every collector returns what it found *and* where it looked, so a control that
fails can point at a path rather than at a verdict.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "build",
        "dist",
        ".tox",
        ".eggs",
        "site-packages",
        "workdirs",
        "vendor",
        "third_party",
        "htmlcov",
    }
)


@dataclass
class Evidence:
    """Everything observed about one repository."""

    name: str
    root: Path
    exists: bool = True

    readme: str | None = None
    readme_path: str | None = None
    headings: list[str] = field(default_factory=list)

    pyproject: dict = field(default_factory=dict)
    pyproject_path: str | None = None
    declared_dependencies: list[str] = field(default_factory=list)
    declared_optional: dict[str, list[str]] = field(default_factory=dict)

    python_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    imported_modules: set[str] = field(default_factory=set)

    local_packages: set[str] = field(default_factory=set)

    has_git: bool = False
    has_remote: bool = False
    has_license: bool = False
    has_ci: bool = False
    tracked_junk: list[str] = field(default_factory=list)

    @property
    def source_files(self) -> list[str]:
        tests = set(self.test_files)
        return [p for p in self.python_files if p not in tests]


def _iter_python(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        out.append(p)
    return sorted(out)


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        any(p in ("tests", "test") for p in parts)
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _top_level_imports(text: str) -> set[str]:
    """Top-level module names imported by this file, via the AST.

    A regex was the first attempt and it was wrong in a way that took the
    `imports-declared` control to a meaningless 0%: `import\\s+([\\w.,\\s]+)`
    has `\\s` inside the character class, so `import json` consumed the
    following lines and reported `sys`, `from` and whatever came next as
    imported names. It also reported `Field` from `from pydantic import Field`
    as a module. `ast` gets both right and costs nothing.

    A file that does not parse contributes no imports rather than failing the
    audit - the repository being audited is not required to be valid Python.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        # level > 0 is a relative import: local, never a dependency.
        elif isinstance(node, ast.ImportFrom) and (node.level or 0) == 0 and node.module:
            found.add(node.module.split(".")[0])
    return {m for m in found if m and not m.startswith("_")}


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


JUNK_PATTERNS = (
    re.compile(r"(^|/)\.venv/"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.log$"),
    re.compile(r"(^|/)node_modules/"),
    re.compile(r"(^|/)\.DS_Store$"),
)


SRC_ROOTS = ("src", "lib")


def _local_packages(root: Path, ev: Evidence) -> set[str]:
    """Package names this repository provides itself.

    A repo importing its own package is not importing a dependency. With a
    `src/` layout the top-level path component is `src`, so taking the first
    path element flagged `ragforge`, `cartographer` and `urdunlp` as
    undeclared third-party imports in the first run.
    """
    names: set[str] = set()

    for rel in ev.python_files:
        parts = rel.split("/")
        if parts[0] in SRC_ROOTS and len(parts) >= 2:
            names.add(parts[1].removesuffix(".py"))
        elif len(parts) >= 2:
            names.add(parts[0])
        else:
            names.add(parts[0].removesuffix(".py"))

    project = ev.pyproject.get("project", {})
    if isinstance(project.get("name"), str):
        names.add(project["name"].replace("-", "_"))

    build = ev.pyproject.get("tool", {}).get("uv", {}).get("build-backend", {})
    if isinstance(build.get("module-name"), str):
        names.add(build["module-name"])

    return {n for n in names if n and n not in SRC_ROOTS}


def collect(root: Path) -> Evidence:
    """Gather every fact the controls might need, once."""
    root = root.resolve()
    ev = Evidence(name=root.name, root=root, exists=root.is_dir())
    if not ev.exists:
        return ev

    for candidate in ("README.md", "readme.md", "README.rst", "README"):
        path = root / candidate
        if path.is_file():
            ev.readme = path.read_text(encoding="utf-8", errors="replace")
            ev.readme_path = candidate
            ev.headings = [
                line.lstrip("#").strip()
                for line in ev.readme.splitlines()
                if line.startswith("#")
            ]
            break

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        ev.pyproject_path = "pyproject.toml"
        try:
            ev.pyproject = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            ev.pyproject = {}
        project = ev.pyproject.get("project", {})
        ev.declared_dependencies = list(project.get("dependencies", []) or [])
        ev.declared_optional = {
            k: list(v) for k, v in (project.get("optional-dependencies", {}) or {}).items()
        }

    for path in _iter_python(root):
        rel = path.relative_to(root).as_posix()
        ev.python_files.append(rel)
        if _is_test(rel):
            ev.test_files.append(rel)
        try:
            ev.imported_modules |= _top_level_imports(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue

    ev.local_packages = _local_packages(root, ev)

    ev.has_git = (root / ".git").exists()
    if ev.has_git:
        ev.has_remote = bool((_git(root, "remote") or "").strip())
        tracked = _git(root, "ls-files") or ""
        ev.tracked_junk = [
            line for line in tracked.splitlines() if any(p.search(line) for p in JUNK_PATTERNS)
        ]

    ev.has_license = any((root / n).is_file() for n in ("LICENSE", "LICENSE.md", "LICENCE"))
    ev.has_ci = (root / ".github" / "workflows").is_dir()
    return ev
