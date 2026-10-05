"""Reading real repositories, and the facts a README claim can be checked against.

Points at the folder named by `REPOS_ROOT` (default `~/code`) — a set of real
checkouts, with their real READMEs, real `pyproject.toml` files and real test
suites. Nothing here is a fixture.

A "fact" is something collected by looking, never inferred: the declared
`requires-python`, the declared dependencies, the number of tests pytest would
collect, whether a git remote exists. A claim is checkable exactly when a fact
answers it.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("REPOS_ROOT") or Path.home() / "code").expanduser()

# A README sentence, roughly. Splitting on markdown structure first keeps a
# table row or a bullet from being glued onto the paragraph above it.
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`\[])")
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_BADGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML = re.compile(r"<[^>]+>")


@dataclass
class Repo:
    path: Path
    name: str
    readme: str = ""
    facts: dict = field(default_factory=dict)

    @property
    def claims(self) -> list[str]:
        return sentences(self.readme)


def _strip(markdown: str) -> str:
    out = _CODE_FENCE.sub(" ", markdown)
    out = _BADGE.sub(" ", out)
    return _HTML.sub(" ", out)


def sentences(markdown: str) -> list[str]:
    """Candidate claims from a README.

    Code blocks, badges and raw HTML are removed first: a badge saying
    "tests 376" is generated from a template and is not a sentence anyone wrote.
    """
    out: list[str] = []
    for block in _strip(markdown).split("\n"):
        line = block.strip().lstrip("#>-*| ").strip()
        if len(line) < 20:
            continue
        out.extend(s.strip() for s in _SENTENCE.split(line) if len(s.strip()) >= 20)
    return out


def _collected_tests(path: Path) -> int | None:
    """What pytest would actually collect.

    Deliberately not a count of `def test_` lines: parametrised tests make the
    two differ, which is recorded in this portfolio's own index.
    """
    if not (path / "tests").exists() and not list(path.glob("*/tests")):
        return None
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-q"],
            cwd=path, capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    return int(match.group(1)) if match else None


def facts_for(path: Path, *, run_pytest: bool = False) -> dict:
    """Everything collectable about a repository, by looking at it."""
    out: dict = {"name": path.name, "root": str(path)}
    projects = path / "projects"
    if projects.exists():
        out["project_count"] = sum(1 for d in projects.iterdir() if d.is_dir())

    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            out["requires_python"] = project.get("requires-python", "")
            out["dependencies"] = list(project.get("dependencies", []) or [])
        except (tomllib.TOMLDecodeError, OSError):
            pass

    out["has_remote"] = (path / ".git").exists() and bool(
        subprocess.run(
            ["git", "remote"], cwd=path, capture_output=True, text=True, check=False
        ).stdout.strip()
    )
    out["python_files"] = sum(1 for _ in path.rglob("*.py") if ".venv" not in str(_))
    if run_pytest:
        collected = _collected_tests(path)
        if collected is not None:
            out["collected_tests"] = collected
    return out


@lru_cache(maxsize=1)
def scan(root: str | None = None, run_pytest: bool = False) -> tuple[Repo, ...]:
    """Every checkout under ``root`` that has a README."""
    base = Path(root) if root else ROOT
    out: list[Repo] = []
    for path in sorted(p for p in base.iterdir() if p.is_dir()):
        if path.name.startswith((".", "_")):
            continue
        readme = path / "README.md"
        if not readme.exists():
            continue
        out.append(
            Repo(
                path=path,
                name=path.name,
                readme=readme.read_text(encoding="utf-8", errors="replace"),
                facts=facts_for(path, run_pytest=run_pytest),
            )
        )
    return tuple(out)
