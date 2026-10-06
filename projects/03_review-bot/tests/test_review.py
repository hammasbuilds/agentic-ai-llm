"""Tests for the propose-then-disprove pipeline.

Most assertions are about *retraction*. Confirming a real bug is the easy
half; the half that decides whether anyone leaves the bot enabled is refusing
to post the plausible-looking ones.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from reviewbot.checks import propose
from reviewbot.cli import main as cli_main
from reviewbot.review import added_lines, render, review_diff, review_source
from reviewbot.verify import FileContext, verify


def src(text: str) -> str:
    return textwrap.dedent(text).lstrip()


def rules_of(code: str) -> list[str]:
    return [p.rule for p in propose(src(code))]


def review(code: str, path: str = "app.py"):
    return review_source(path, src(code))


def confirmed_rules(code: str, path: str = "app.py") -> list[str]:
    return [v.rule for v in review(code, path).confirmed]


def retracted_reasons(code: str, path: str = "app.py") -> list[str]:
    return [v.reason for v in review(code, path).retracted]


# -- proposers fire -------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "rule"),
    [
        ("def f(a=[]):\n    a.append(1)\n", "mutable-default"),
        ("def f(a=dict()):\n    a['x'] = 1\n", "mutable-default"),
        ("try:\n    pass\nexcept:\n    pass\n", "bare-except"),
        ("try:\n    pass\nexcept Exception:\n    pass\n", "swallowed-exception"),
        ("if x == None:\n    pass\n", "eq-none"),
        ("if x == True:\n    pass\n", "eq-bool"),
        ("f = open('x')\n", "open-without-with"),
        ("assert x\n", "assert-in-source"),
        ("for i in items:\n    items.append(i)\n", "mutate-while-iterating"),
    ],
)
def test_proposers_fire(code: str, rule: str):
    assert rule in rules_of(code)


def test_an_unparseable_file_proposes_nothing():
    assert propose("def f(:\n") == []


# -- verifiers defeat the plausible ones ---------------------------------


def test_a_mutable_default_that_is_never_mutated_is_retracted():
    """Sharing a default between calls is only observable if it is mutated."""
    code = """
        def f(a=[]):
            return len(a)
    """
    assert "mutable-default" in rules_of(code)
    assert "mutable-default" not in confirmed_rules(code)


def test_a_mutable_default_that_is_mutated_is_confirmed():
    code = """
        def f(a=[]):
            a.append(1)
            return a
    """
    assert "mutable-default" in confirmed_rules(code)


def test_a_bare_except_that_reraises_is_retracted():
    code = """
        try:
            work()
        except:
            cleanup()
            raise
    """
    assert "bare-except" in rules_of(code)
    assert "bare-except" not in confirmed_rules(code)


def test_a_bare_except_that_swallows_is_confirmed():
    code = """
        try:
            work()
        except:
            pass
    """
    assert "bare-except" in confirmed_rules(code)


def test_open_inside_a_with_statement_is_retracted():
    code = "with open('x') as fh:\n    fh.read()\n"
    assert "open-without-with" in rules_of(code)
    assert "open-without-with" not in confirmed_rules(code)


def test_open_consumed_immediately_is_retracted():
    code = "text = open('x').read()\n"
    assert "open-without-with" not in confirmed_rules(code)


def test_a_retained_handle_is_confirmed():
    code = "fh = open('x')\nuse(fh)\n"
    assert "open-without-with" in confirmed_rules(code)


def test_eq_none_is_retracted_in_a_query_dsl():
    """SQLAlchemy overloads __eq__; `is None` would be wrong there."""
    code = """
        from sqlalchemy import select

        q = select(User).where(User.deleted_at == None)
    """
    assert "eq-none" in rules_of(code)
    assert "eq-none" not in confirmed_rules(code)


def test_eq_none_is_confirmed_in_plain_python():
    code = "if value == None:\n    pass\n"
    assert "eq-none" in confirmed_rules(code)


def test_asserts_are_retracted_in_test_files():
    assert "assert-in-source" not in confirmed_rules("assert x == 1\n", "tests/test_a.py")


def test_asserts_are_confirmed_in_source_files():
    assert "assert-in-source" in confirmed_rules("assert x == 1\n", "src/app.py")


@pytest.mark.parametrize("marker", ["noqa", "nosec", "intentional", "deliberate"])
def test_an_acknowledged_finding_is_retracted(marker: str):
    """Re-raising something the author already marked is what gets a bot muted."""
    code = f"fh = open('x')  # {marker}\n"
    assert not review(code).confirmed


def test_a_swallowed_exception_with_an_explanation_is_retracted():
    code = """
        try:
            optional_step()
        except Exception:  # best effort, failure here is fine
            pass
    """
    assert "swallowed-exception" not in confirmed_rules(code)


def test_every_retraction_states_a_reason():
    code = "with open('x') as fh:\n    fh.read()\n"
    reasons = retracted_reasons(code)
    assert reasons and all(r.strip() for r in reasons)


def test_a_confirmed_verdict_says_no_defeater_applied():
    context = FileContext.build("app.py", "fh = open('x')\nuse(fh)\n")
    proposal = propose("fh = open('x')\nuse(fh)\n")[0]
    verdict = verify(context, proposal)
    assert verdict.confirmed
    assert verdict.reason == "no defeater applied"


# -- diff scoping ---------------------------------------------------------


DIFF = textwrap.dedent("""
    diff --git a/app.py b/app.py
    --- a/app.py
    +++ b/app.py
    @@ -1,0 +2,1 @@
    +fh = open('new.txt')
""").lstrip()


def test_added_lines_are_parsed():
    assert added_lines(DIFF) == {"app.py": {2}}


def test_a_deleted_file_contributes_no_lines():
    diff = "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
    assert added_lines(diff) == {}


def test_findings_outside_the_diff_are_not_reported():
    """A reviewer that comments on untouched code is auditing, not reviewing."""
    code = src("""
        old = open('a')
        use(old)
        new = open('b')
        use(new)
    """)
    only_line_three = review_source("app.py", code, changed_lines={3})
    lines = [v.proposal.line for v in only_line_three.verdicts]
    assert lines == [3]


def test_verification_still_reads_the_whole_file():
    """The defeater lives outside the changed hunk, and must still be found."""
    code = src("""
        from sqlalchemy import select
        q = select(User).where(User.x == None)
    """)
    result = review_source("q.py", code, changed_lines={2})
    assert result.verdicts
    assert not result.confirmed  # the sqlalchemy import on line 1 defeated it


# -- aggregate reporting --------------------------------------------------


def test_retraction_rate_is_reported():
    code = src("""
        with open('a') as fh:
            fh.read()
        kept = open('b')
        use(kept)
    """)
    result = review_source("app.py", code)
    from reviewbot.review import Review

    review_all = Review(files=[result])
    assert review_all.proposed == 2
    assert review_all.confirmed == 1
    assert review_all.retraction_rate == 0.5


def test_render_names_the_retraction_rate():
    from reviewbot.review import Review

    text = render(Review(files=[review_source("app.py", "fh = open('x')\nuse(fh)\n")]))
    assert "retracted" in text


def test_an_empty_review_does_not_divide_by_zero():
    from reviewbot.review import Review

    assert Review().retraction_rate == 0.0


# -- against a real repository -------------------------------------------


@pytest.mark.slow
def test_review_diff_runs_against_a_real_commit(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)

    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "one"], check=True)

    (repo / "app.py").write_text("x = 1\nfh = open('y')\nuse(fh)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "two"], check=True)

    result = review_diff(repo, "HEAD~1")
    assert result.confirmed == 1


# -- the denominator the scan never printed -------------------------------


def _repo(tmp_path: Path) -> Path:
    """Two source files and a test file, so the skip count is not zero."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "clean.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "smelly.py").write_text(
        "def f(path):\n    try:\n        h = open(path)\n    except:\n        pass\n"
        "    return h\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_f():\n    assert 1 == 1\n", encoding="utf-8"
    )
    return tmp_path


def test_the_scan_prints_the_file_count_its_rate_is_over(tmp_path, capsys):
    """It printed per-rule proposals and confirmations and no total at all.

    The README quoted "SOURCE FILES ONLY: files=1,325  proposed=476 ..." in a format
    this command never produced, so the headline retraction rate had no source in the
    tool that computes it, and the file count was not available to produce.
    """
    from reviewbot.cli import main

    assert main(["scan", str(_repo(tmp_path))]) == 0
    out = capsys.readouterr().out

    assert "SOURCE FILES ONLY: files=2" in out
    assert "proposed=" in out and "confirmed=" in out and "retracted=" in out
    assert "(1 test files skipped; pass --include-tests to review them)" in out


def test_including_tests_says_so_and_counts_them(tmp_path, capsys):
    """Because the 99% figure in the README is the --include-tests run."""
    from reviewbot.cli import main

    assert main(["scan", str(_repo(tmp_path)), "--include-tests"]) == 0
    out = capsys.readouterr().out
    assert "ALL FILES: files=3" in out
    assert "test files skipped" not in out


def test_the_json_carries_the_denominator_too(tmp_path):
    import json

    from reviewbot.cli import main

    target = _repo(tmp_path)
    out = tmp_path / "scan.json"
    assert main(["scan", str(target), "--json", str(out)]) == 0
    held = json.loads(out.read_text(encoding="utf-8"))

    assert held["files_reviewed"] == 2
    assert held["test_files_skipped"] == 1
    assert held["files_unreadable"] == 0
    assert held["proposed"] == held["confirmed"] + held["retracted"]


def test_a_review_of_nothing_is_refused_rather_than_reported(tmp_path, capsys):
    """This test used to assert the opposite, and the opposite was wrong.

    It read "an empty folder gives 0 of 0 rather than a rate over nothing" and checked
    for `files=0` and exit 0. But `files=0 proposed=0 confirmed=0 retracted=0 (0%)` IS
    a rate over nothing, and 0% retracted is this tool's best possible result printed
    for a folder it never looked at. An independent review reached it through the shape
    that matters - `scan` on a path that does not exist - where `rglob` yields nothing
    and the output is identical. A typo was reported as a clean review.

    So the refusal is the behaviour, and exit 2 is how a caller tells the two apart.
    """
    from reviewbot.cli import main

    assert main(["scan", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "nothing to review" in captured.err
    assert "files=" not in captured.out, captured.out


def test_a_path_that_does_not_exist_is_refused(tmp_path, capsys):
    """The shape the review used. It is not the same bug as an empty folder - this one
    cannot be a real review at all - but it printed the same thing."""
    from reviewbot.cli import main

    assert main(["scan", str(tmp_path / "nope")]) == 2
    captured = capsys.readouterr()
    assert "no such file or directory" in captured.err
    assert "files=" not in captured.out, captured.out


def test_a_file_that_is_not_python_is_refused(tmp_path, capsys):
    """`scan README.md` used to review the file as Python, fail to parse it, and print
    `files=0` with one unparseable - a 0% retraction rate over a markdown file."""
    from reviewbot.cli import main

    readme = tmp_path / "README.md"
    readme.write_text("# notes\n", encoding="utf-8")
    assert main(["scan", str(readme)]) == 2
    assert "not Python" in capsys.readouterr().err


def test_one_python_file_is_still_reviewable(tmp_path, capsys):
    """A refusal that refuses the working case is not a fix."""
    from reviewbot.cli import main

    one = tmp_path / "m.py"
    one.write_text("def f(x=[]):\n    return x\n", encoding="utf-8")
    assert main(["scan", str(one)]) == 0
    assert "files=1" in capsys.readouterr().out


# -- a file no rule could run over is not a reviewed file ---------------------


def test_an_unparseable_file_is_not_counted_as_reviewed(tmp_path, capsys):
    """`propose` returned `[]` on SyntaxError, which reads as "reviewed, found nothing".

    So `files=` counted work that did not happen. On the published scan two files in the
    surveyed folder are not parseable by this interpreter, and both sat in the
    denominator of every per-file figure looking exactly like clean code.
    """
    (tmp_path / "clean.py").write_text("def f(x=[]):\n    return x\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "notpython.py").write_text("this is not python at all ((\n", encoding="utf-8")

    assert cli_main(["scan", str(tmp_path)]) == 0
    out = capsys.readouterr().out

    assert "files=1" in out, out
    assert "2 file(s) are not parseable Python and are not in that count" in out, out
    assert "broken.py" in out and "notpython.py" in out, out


def test_the_unparseable_count_is_in_the_json(tmp_path):
    """The figure a reader would quote, in the machine-readable output too."""
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    out = tmp_path / "scan.json"

    assert cli_main(["scan", str(tmp_path), "--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["files_reviewed"] == 1
    assert data["files_unparseable"] == 1


def test_review_source_says_whether_it_parsed(tmp_path):
    """The state the CLI counts on, asserted where it is produced."""
    assert review_source("a.py", "x = 1\n").parsed is True
    assert review_source("b.py", "def broken(:\n").parsed is False
    # And an unparseable file proposes nothing, which is why the two looked alike.
    assert review_source("b.py", "def broken(:\n").verdicts == []
