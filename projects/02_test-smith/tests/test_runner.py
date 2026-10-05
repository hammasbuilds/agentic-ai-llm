"""Runner tests.

These build tiny repositories on disk and actually run pytest inside them.
Mocking the subprocess would test the mock: the behaviour that matters here is
whether a real suite, run against real mutated source, returns the verdict we
think it does.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from testsmith.runner import ERROR, KILLED, SURVIVED, run, source_files


def write(root: Path, rel: str, source: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


def make_repo(tmp_path: Path, code: str, tests: str) -> Path:
    root = tmp_path / "demo"
    write(root, "src/demo/__init__.py", "")
    write(root, "src/demo/core.py", code)
    write(root, "tests/test_core.py", tests)
    return root


# -- file selection -------------------------------------------------------


def test_test_files_are_not_mutated(tmp_path: Path):
    """A mutated assertion fails its own test and scores as a kill, proving nothing."""
    root = make_repo(
        tmp_path, "def f(a):\n    return a + 1\n", "def test_x():\n    assert True\n"
    )
    write(root, "conftest.py", "")
    picked = {p.name for p in source_files(root)}
    assert "core.py" in picked
    assert "test_core.py" not in picked
    assert "conftest.py" not in picked


def test_caches_and_venvs_are_not_mutated(tmp_path: Path):
    root = make_repo(tmp_path, "def f():\n    return 1\n", "def test_x():\n    assert True\n")
    write(root, ".venv/lib/thing.py", "def g():\n    return 2\n")
    write(root, "__pycache__/x.py", "def h():\n    return 3\n")
    assert {p.name for p in source_files(root)} == {"core.py", "__init__.py"}


# -- verdicts -------------------------------------------------------------


@pytest.mark.slow
def test_a_strong_test_kills_the_mutant(tmp_path: Path):
    root = make_repo(
        tmp_path,
        "def add(a, b):\n    return a + b\n",
        "from demo.core import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    report = run(root, limit=4)
    outcomes = {r.outcome for r in report.results}
    assert KILLED in outcomes
    assert report.score > 0


@pytest.mark.slow
def test_a_weak_test_lets_the_mutant_live(tmp_path: Path):
    """The test runs the line and asserts nothing about the result."""
    root = make_repo(
        tmp_path,
        "def add(a, b):\n    return a + b\n",
        "from demo.core import add\n\ndef test_add():\n    add(2, 3)\n",
    )
    report = run(root, limit=4)
    assert all(r.outcome in (SURVIVED, ERROR) for r in report.results)
    assert report.score == 0.0


@pytest.mark.slow
def test_the_original_repository_is_never_written_to(tmp_path: Path):
    """The whole run happens in a copy. This is the safety property that matters."""
    root = make_repo(
        tmp_path,
        "def add(a, b):\n    return a + b\n",
        "from demo.core import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    target = root / "src" / "demo" / "core.py"
    before = target.read_text(encoding="utf-8")
    mtime = target.stat().st_mtime_ns
    run(root, limit=6)
    assert target.read_text(encoding="utf-8") == before
    assert target.stat().st_mtime_ns == mtime


@pytest.mark.slow
def test_a_red_suite_is_refused(tmp_path: Path):
    """A mutation score against a failing suite is meaningless, so refuse to produce one."""
    root = make_repo(
        tmp_path,
        "def add(a, b):\n    return a + b\n",
        "from demo.core import add\n\ndef test_add():\n    assert add(2, 3) == 99\n",
    )
    with pytest.raises(RuntimeError, match="does not pass before mutation"):
        run(root, limit=2)


# -- the coverage split ---------------------------------------------------


@pytest.mark.slow
def test_survivors_split_by_whether_the_line_ran(tmp_path: Path):
    """The project's reason to exist, as an assertion.

    `used` is executed by the test but its result is never checked, so its
    mutants survive on a *covered* line. `never_called` is not executed at all,
    so its mutants survive on an *uncovered* line. A coverage report shows one
    of these problems; mutation testing shows both, and distinguishes them.
    """
    root = make_repo(
        tmp_path,
        """
        def used(a):
            return a + 1

        def never_called(a):
            return a * 2
        """,
        "from demo.core import used\n\ndef test_used():\n    used(1)\n",
    )
    report = run(root, limit=None)
    assert report.coverage is not None

    covered = {r.mutant.line for r in report.survivors_on_covered_lines}
    uncovered = {r.mutant.line for r in report.survivors_on_uncovered_lines}
    assert covered, "the executed-but-unchecked line should have survivors"
    assert uncovered, "the never-executed line should have survivors"
    assert not (covered & uncovered), "a line cannot be both"


@pytest.mark.slow
def test_import_errors_are_excluded_rather_than_counted_as_kills(tmp_path: Path):
    """Counting collection errors as kills is how mutation scores get inflated."""
    root = make_repo(
        tmp_path,
        "def add(a, b):\n    return a + b\n",
        "from demo.core import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    report = run(root, limit=6)
    assert report.scored == len([r for r in report.results if r.outcome != ERROR])
    assert report.scored <= len(report.results)


def test_score_is_zero_when_nothing_was_scored():
    from testsmith.runner import RunReport

    empty = RunReport(
        repo="x", interpreter=sys.executable, baseline_seconds=0.1, total_mutants=0
    )
    assert empty.score == 0.0
    assert empty.covered_score == 0.0


# --- the exclusion that can only move the score up ------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import nonexistent_module_xyz\n\n\ndef test_x():\n    assert True\n", True),
        (
            "def test_x():\n    assert 'a' == 'ImportError: no such module', 'ImportError'\n",
            False,
        ),
        (
            "import pytest\n\n\n"
            "def test_x():\n"
            "    with pytest.raises(ModuleNotFoundError):\n"
            "        import nonexistent_inner_xyz\n"
            "    assert 1 == 2\n",
            False,
        ),
        ("def test_x():\n    assert 1 == 2\n", False),
    ],
)
def test_only_a_real_collection_failure_is_excluded(tmp_path: Path, source, expected):
    """`ImportError` was substring-matched against the whole pytest output.

    The exclusion is applied only to a mutant that would otherwise be KILLED, and
    `RunReport.scored` drops it from numerator *and* denominator — so a false positive
    can only push the score up. A suite whose own assertion message contains the word,
    or which asserts on a raised ImportError, had its kills quietly removed: on a
    constructed repo the tool reported 100% over one scored mutant.

    Driven through real pytest rather than a hand-written string, because the question
    is what pytest actually prints.
    """
    import subprocess
    import sys as _sys

    from testsmith.runner import _looks_like_collection_error

    (tmp_path / "test_it.py").write_text(source, encoding="utf-8")
    done = subprocess.run(
        [_sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = done.stdout + done.stderr
    assert _looks_like_collection_error(output, done.returncode) is expected, output[-400:]
