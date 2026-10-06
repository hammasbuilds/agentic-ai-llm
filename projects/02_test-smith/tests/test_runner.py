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

    Run from inside `tmp_path` with `.` as the argument, not from here with the absolute
    path. `tmp_path` lives under the user-wide temp directory, which on a shared machine
    other processes are creating and deleting directories in; pytest's own collection
    walked an entry there that vanished between the listing and the `lstat`, and printed
    `FileNotFoundError ... Interrupted: 1 error during collection`. The two cases
    expecting `False` then failed - correctly, since the output really did contain a
    collection error, just not the one under test. Making `tmp_path` the rootdir keeps
    the subprocess from looking above it, so the only output is the one this asserts on.
    """
    import subprocess
    import sys as _sys

    from testsmith.runner import _looks_like_collection_error

    (tmp_path / "test_it.py").write_text(source, encoding="utf-8")
    done = subprocess.run(
        [_sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "."],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = done.stdout + done.stderr
    assert _looks_like_collection_error(output, done.returncode) is expected, output[-400:]


# -- a coverage measurement that failed is not a clean one ----------------


def test_a_failed_coverage_measurement_says_so_rather_than_reporting_zero(tmp_path):
    """`Coverage(lines={})` was returned for a crash, a timeout and a clean run that
    covered nothing, and the report turned all three into "0% over 0 mutants" followed
    by "none - every executed line that could be mutated was checked". A success
    sentence over zero observations, exit 0.
    """
    import os
    import sys

    from testsmith.coverage import measure

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_slow.py").write_text(
        "import time"
        + chr(10) * 2
        + "def test_slow():"
        + chr(10)
        + "    time.sleep(30)"
        + chr(10),
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(tmp_path))

    timed_out = measure(sys.executable, tmp_path, env, timeout=2)
    assert timed_out.measured is False
    assert "did not finish within 2s" in timed_out.failure
    assert timed_out.lines == {}

    crashed = measure("C:/no/such/python.exe", tmp_path, env, timeout=10)
    assert crashed.measured is False
    assert crashed.failure, "a crash has to say what it was"


def test_a_clean_measurement_of_nothing_is_distinguishable_from_a_failure():
    from testsmith.coverage import Coverage

    nothing_ran = Coverage(lines={}, failure="the suite did not finish within 2s")
    ran_covered_nothing = Coverage(lines={})

    assert nothing_ran.measured is False
    assert ran_covered_nothing.measured is True
    assert nothing_ran.total == ran_covered_nothing.total == 0, (
        "the two are identical in every field the report used to read"
    )


def test_the_report_refuses_to_claim_a_clean_run_when_coverage_failed():
    from testsmith.coverage import Coverage
    from testsmith.report import render_text

    class _Report:
        repo = "demo"
        total_mutants = 4
        baseline_seconds = 1.0
        killed = 2
        survived = 2
        timed_out = 0
        errored = 0
        score = 0.5
        scored = 4
        covered_score = 0.0
        covered_mutants = 0
        coverage_measured = False
        coverage_failure = "the suite did not finish within 2s"
        survivors_on_covered_lines: list = []
        survivors_on_uncovered_lines: list = []
        results: list = []
        by_operator: dict = {}
        coverage = Coverage(lines={}, failure="the suite did not finish within 2s")

    text = render_text(_Report())
    assert "on executed lines  not measured" in text
    assert "did not finish within 2s" in text
    assert "every executed line that could be mutated was checked" not in text
    assert "not measured - there is no coverage to restrict the mutants to." in text


def test_the_sweep_script_refuses_an_empty_corpus(tmp_path):
    """It printed "missing" eight times, skipped its own table and exited 0.

    The default root was `~/code`, which exists on no machine this was measured on,
    so the command the README offers as "reproduces the table above" reproduced
    nothing and said so only in the sense that each line read `missing`. `rows` was
    empty, lines 55-76 were skipped, and the exit code was green.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, str(root / "scripts" / "sweep.py"), "2"],
        cwd=root,
        capture_output=True,
        text=True,
        env={
            "REPOS_ROOT": str(tmp_path),
            "PATH": __import__("os").environ.get("PATH", ""),
            "PYTHONPATH": str(root / "src"),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
        timeout=300,
    )
    assert done.returncode == 1, f"an empty sweep exited {done.returncode}"
    assert "No repository was measured" in done.stderr
    assert str(tmp_path) in done.stderr, "it has to name where it looked"
    assert "REPOS_ROOT" in done.stderr


def test_the_sweep_default_is_the_folder_this_repository_sits_in():
    """Rather than `~/code`, which is why the documented command measured nothing."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts" / "sweep.py").read_text(
        encoding="utf-8"
    )
    assert 'Path.home() / "code"' not in source
    assert "parents[3].parent" in source
