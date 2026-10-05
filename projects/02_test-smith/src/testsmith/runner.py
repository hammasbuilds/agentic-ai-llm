"""Run a test suite against mutated source and record what it caught.

Nothing here writes to the repository being measured. The repo is copied into a
scratch workspace once, mutations are applied to that copy, and the original
tree is never opened for writing. A mutation run that corrupts the code it is
grading would be worse than no mutation run at all.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .coverage import Coverage, measure
from .mutate import Mutant, generate

__all__ = [
    "ERROR",
    "KILLED",
    "SURVIVED",
    "TIMEOUT",
    "MutantResult",
    "RunReport",
    "find_interpreter",
    "operator_summary",
    "run",
    "source_files",
]

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
        ".testsmith",
        "htmlcov",
        ".idea",
        ".vscode",
    }
)

KILLED = "killed"
SURVIVED = "survived"
TIMEOUT = "timeout"
ERROR = "error"


@dataclass
class MutantResult:
    mutant: Mutant
    outcome: str
    seconds: float

    @property
    def caught(self) -> bool:
        # A timeout means the mutant caused a hang the suite noticed. That is a
        # kill: the change did not slip through silently.
        return self.outcome in (KILLED, TIMEOUT)


@dataclass
class RunReport:
    repo: str
    interpreter: str
    baseline_seconds: float
    total_mutants: int
    results: list[MutantResult] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    coverage: Coverage | None = None

    def _on_covered_line(self, r: MutantResult) -> bool:
        if self.coverage is None:
            return False
        return self.coverage.executed(r.mutant.path, r.mutant.line)

    @property
    def survivors_on_covered_lines(self) -> list[MutantResult]:
        """The finding. The test executed this line and did not notice it was wrong.

        A coverage report marks these lines green. They are not tested; they are
        merely visited.
        """
        return [r for r in self.results if r.outcome == SURVIVED and self._on_covered_line(r)]

    @property
    def survivors_on_uncovered_lines(self) -> list[MutantResult]:
        """Survivors no test ever reached. A coverage problem, not a test-quality one."""
        return [
            r for r in self.results if r.outcome == SURVIVED and not self._on_covered_line(r)
        ]

    @property
    def covered_score(self) -> float:
        """Mutation score restricted to lines the suite actually executes.

        This is the honest measure of test *strength*. The unrestricted score
        conflates "we never ran this code" with "we ran it and did not check it".
        """
        pool = [r for r in self.results if r.outcome != ERROR and self._on_covered_line(r)]
        if not pool:
            return 0.0
        return sum(1 for r in pool if r.caught) / len(pool)

    @property
    def covered_mutants(self) -> int:
        return sum(1 for r in self.results if r.outcome != ERROR and self._on_covered_line(r))

    @property
    def killed(self) -> int:
        return sum(1 for r in self.results if r.outcome == KILLED)

    @property
    def survived(self) -> int:
        return sum(1 for r in self.results if r.outcome == SURVIVED)

    @property
    def timed_out(self) -> int:
        return sum(1 for r in self.results if r.outcome == TIMEOUT)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.outcome == ERROR)

    @property
    def scored(self) -> int:
        """Mutants that produced a usable verdict.

        A mutant whose module fails to import is not evidence about the tests,
        so it is excluded rather than counted as a kill. Counting import errors
        as kills is the standard way mutation scores get inflated.
        """
        return sum(1 for r in self.results if r.outcome != ERROR)

    @property
    def score(self) -> float:
        if self.scored == 0:
            return 0.0
        return sum(1 for r in self.results if r.caught) / self.scored

    @property
    def by_operator(self) -> dict[str, tuple[int, int]]:
        """operator -> (caught, scored)"""
        out: dict[str, list[int]] = {}
        for r in self.results:
            if r.outcome == ERROR:
                continue
            slot = out.setdefault(r.mutant.operator, [0, 0])
            slot[1] += 1
            if r.caught:
                slot[0] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}

    def survivors(self, limit: int = 20) -> list[MutantResult]:
        return [r for r in self.results if r.outcome == SURVIVED][:limit]


def find_interpreter(repo: Path) -> str:
    """Prefer the repo's own virtualenv - its tests need its dependencies."""
    for candidate in (
        repo / ".venv" / "Scripts" / "python.exe",
        repo / ".venv" / "bin" / "python",
        repo / "venv" / "Scripts" / "python.exe",
        repo / "venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def source_files(repo: Path) -> list[Path]:
    """Python files worth mutating: source, not tests and not config.

    Mutating a test file measures nothing - a mutated assertion fails its own
    test and scores as a kill while telling you nothing about the code.
    """
    out: list[Path] = []
    for p in repo.rglob("*.py"):
        parts = p.relative_to(repo).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if any(part in ("tests", "test") for part in parts):
            continue
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        if p.name in ("conftest.py", "setup.py"):
            continue
        out.append(p)
    return sorted(out)


def _copy_workspace(repo: Path, dest: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SKIP_DIRS}

    shutil.copytree(repo, dest, ignore=ignore, dirs_exist_ok=True)


def _pytest_env(workspace: Path) -> dict[str, str]:
    """Force imports to resolve inside the workspace, not the original checkout.

    An editable install points at the original source tree. Without putting the
    workspace first on PYTHONPATH the tests would import unmutated code and
    every mutant would survive - a silent, total false negative.
    """
    env = dict(os.environ)
    roots = [str(workspace / "src"), str(workspace)]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        os.pathsep.join([*roots, existing]) if existing else os.pathsep.join(roots)
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_suite(
    interpreter: str, workspace: Path, timeout: float, fail_fast: bool
) -> tuple[int, str]:
    cmd = [interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"]
    if fail_fast:
        cmd.append("-x")
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            env=_pytest_env(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run(
    repo: Path,
    limit: int | None = None,
    timeout_factor: float = 6.0,
    min_timeout: float = 20.0,
    only: str | None = None,
    progress=None,
) -> RunReport:
    """Measure one repository.

    `limit` caps the number of mutants, sampled evenly across files so a cap
    does not simply measure the alphabetically-first module.
    """
    repo = repo.resolve()
    interpreter = find_interpreter(repo)

    workspace_root = Path(tempfile.mkdtemp(prefix="testsmith-"))
    workspace = workspace_root / repo.name
    try:
        _copy_workspace(repo, workspace)

        started = time.perf_counter()
        code, output = _run_suite(interpreter, workspace, timeout=600, fail_fast=False)
        baseline = time.perf_counter() - started
        if code != 0:
            raise RuntimeError(
                f"the suite does not pass before mutation (exit {code}). "
                f"A mutation score is meaningless against a red suite.\n"
                f"{output[-1200:]}"
            )

        cov = measure(interpreter, workspace, _pytest_env(workspace))

        files = source_files(repo)
        if only:
            files = [f for f in files if only in f.relative_to(repo).as_posix()]

        per_file: list[list[Mutant]] = []
        skipped: list[str] = []
        for f in files:
            rel = f.relative_to(repo).as_posix()
            ms = generate(f, rel)
            if ms:
                per_file.append(ms)
            else:
                skipped.append(rel)

        mutants = _interleave(per_file, limit)
        timeout = max(min_timeout, baseline * timeout_factor)

        report = RunReport(
            repo=repo.name,
            interpreter=interpreter,
            baseline_seconds=round(baseline, 2),
            total_mutants=sum(len(m) for m in per_file),
            skipped_files=skipped,
            coverage=cov,
        )

        for i, mutant in enumerate(mutants, 1):
            target = workspace / mutant.path
            original = target.read_text(encoding="utf-8")
            t0 = time.perf_counter()
            try:
                target.write_text(mutant.source, encoding="utf-8")
                code, output = _run_suite(interpreter, workspace, timeout, fail_fast=True)
                if code == -1:
                    outcome = TIMEOUT
                elif code == 0:
                    outcome = SURVIVED
                elif _looks_like_collection_error(output, code):
                    outcome = ERROR
                else:
                    outcome = KILLED
            finally:
                target.write_text(original, encoding="utf-8")
            elapsed = time.perf_counter() - t0
            report.results.append(MutantResult(mutant, outcome, round(elapsed, 2)))
            if progress:
                progress(i, len(mutants), mutant, outcome)

        return report
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)


#: What pytest prints when it could not collect, rather than when a test failed. Bare
#: "ImportError" and "ModuleNotFoundError" used to be in here, matched against the WHOLE
#: output - so a test whose own assertion message contained the word, or a suite that
#: deliberately asserts on a raised ImportError, had its mutant excluded. The exclusion
#: is only ever applied to a mutant that would otherwise be KILLED and removes it from
#: both numerator and denominator, so a false positive can only push the score UP. On a
#: constructed repo whose test message said "ImportError", the tool reported 100%.
_COLLECTION_MARKERS = (
    "ERROR collecting",
    "error during collection",
    "INTERNALERROR",
    "Interrupted: ",
)


def _looks_like_collection_error(output: str, code: int | None = None) -> bool:
    """Distinguish "the tests caught it" from "the code stopped importing".

    A mutant that breaks collection never reached a single assertion, so it is not
    evidence that the suite is good. Counting these as kills is how mutation scores get
    quietly inflated - and counting a kill as one of these inflates them the same way.

    pytest's own markers only. An import error that stopped collection always produces
    one of them; an import error merely mentioned inside a failure report does not.
    """
    if any(m in output for m in _COLLECTION_MARKERS):
        return True
    # pytest exits 2 when it was interrupted, which is what a collection failure does,
    # and 1 when tests ran and failed. An import error with exit 1 is a test result.
    return code == 2 and ("ImportError" in output or "ModuleNotFoundError" in output)


def _interleave(per_file: list[list[Mutant]], limit: int | None) -> list[Mutant]:
    """Round-robin across files so a cap samples the whole repo."""
    flat: list[Mutant] = []
    if not per_file:
        return flat
    index = 0
    while True:
        added = False
        for group in per_file:
            if index < len(group):
                flat.append(group[index])
                added = True
                if limit is not None and len(flat) >= limit:
                    return flat
        if not added:
            return flat
        index += 1


def operator_summary(report: RunReport) -> Counter:
    return Counter(r.mutant.operator for r in report.results if r.outcome == SURVIVED)
