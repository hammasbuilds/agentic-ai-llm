"""Risk scoring and gate tests.

The commits here are built by hand rather than read from git, because the
point is the scoring function and a fixture repository would only add latency.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from captain.gate import BLOCK, NOT_MEASURED, PASS, WARN, evaluate, render
from captain.history import Commit, FileChange, History
from captain.risk import Baseline, rank_by, rank_disagreement, score_commit

WHEN = datetime(2026, 9, 17, tzinfo=UTC)


def make(sha: str, subject: str, files: list[tuple[str, int, int]]) -> Commit:
    return Commit(
        sha=sha,
        author="t",
        when=WHEN,
        subject=subject,
        files=[FileChange(p, a, d) for p, a, d in files],
    )


BASE = Baseline(median_churn=100.0, median_files=3.0)


# -- the factors ----------------------------------------------------------


def test_a_wide_change_outranks_a_voluminous_one():
    """The finding this project is built on.

    A generated data dump is enormous in lines and trivial in review effort.
    A broad refactor is the reverse. Ranked by lines alone, the dump wins.
    """
    dump = make("a", "regenerate results", [(f"results/r{i}.json", 10000, 0) for i in range(5)])
    refactor = make(
        "b",
        "rename across the package",
        [(f"src/pkg/m{i}.py", 8, 8) for i in range(60)] + [("tests/test_all.py", 5, 5)],
    )
    assert dump.churn > refactor.churn * 5
    assert score_commit(refactor, BASE).score() > score_commit(dump, BASE).score()


def test_untested_source_scores_higher_than_the_same_change_with_tests():
    without = make("a", "fix", [("src/pkg/core.py", 120, 40)])
    with_tests = make("b", "fix", [("src/pkg/core.py", 120, 40), ("tests/test_core.py", 30, 0)])
    assert score_commit(without, BASE).score() > score_commit(with_tests, BASE).score()


def test_an_untested_tiny_change_is_not_ranked_like_an_untested_large_one():
    """The first version scored these identically.

    That ranked a one-line typo fix third-riskiest in mcp-lab, above a
    693-file change, because `untested` ignored how much source had changed.
    """
    tiny = make("a", "typo", [("src/pkg/core.py", 1, 1)])
    large = make("b", "rewrite", [("src/pkg/core.py", 800, 300)])
    tiny_untested = score_commit(tiny, BASE).untested
    large_untested = score_commit(large, BASE).untested
    assert large_untested > tiny_untested * 2


def test_docs_only_commits_score_low():
    docs = make("a", "readme", [("README.md", 200, 50)])
    code = make("b", "code", [("src/pkg/core.py", 200, 50)])
    assert score_commit(docs, BASE).score() < score_commit(code, BASE).score()


def test_volume_compresses_the_range_instead_of_scaling_with_it():
    """A 10,000x larger diff must not be 10,000x the risk.

    An earlier version of this test asserted diminishing returns *per decade*,
    which a log scale does not provide - it gives equal steps per decade by
    construction. The property that actually matters is compression against
    linear, plus a ceiling: without one, a single generated data file would
    saturate any release gate on its own.
    """
    small = score_commit(make("a", "s", [("src/a.py", 10, 0), ("tests/t.py", 1, 0)]), BASE)
    huge = score_commit(make("c", "h", [("src/a.py", 100000, 0), ("tests/t.py", 1, 0)]), BASE)

    line_ratio = 100000 / 10
    volume_ratio = huge.volume / small.volume
    assert volume_ratio < line_ratio / 1000  # 10,000x lines, under 10x volume
    assert huge.volume <= 1.0  # and it cannot exceed the ceiling


def test_volume_steps_evenly_per_decade_until_it_saturates():
    def vol(lines: int) -> float:
        return score_commit(make("x", "s", [("src/a.py", lines, 0)]), BASE).volume

    first = vol(100) - vol(10)
    second = vol(1000) - vol(100)
    assert first == pytest.approx(second, abs=0.02)


def test_factors_sum_to_the_score():
    commit = make("a", "x", [("src/pkg/a.py", 50, 10), ("docs/b.md", 5, 0)])
    factors = score_commit(commit, BASE)
    assert sum(points for _, _, points in factors.explain()) == pytest.approx(
        factors.score(), abs=0.2
    )


def test_explain_is_ordered_by_contribution():
    commit = make("a", "x", [(f"src/area{i}/m.py", 40, 5) for i in range(5)])
    points = [p for _, _, p in score_commit(commit, BASE).explain()]
    assert points == sorted(points, reverse=True)


# -- baselines are relative -----------------------------------------------


def test_the_same_commit_scores_lower_in_a_repo_of_large_commits():
    """A 400-line change is unremarkable where the median is 700."""
    commit = make("a", "x", [("src/pkg/a.py", 300, 100), ("tests/t.py", 10, 0)])
    small_repo = Baseline(median_churn=20.0, median_files=2.0)
    large_repo = Baseline(median_churn=700.0, median_files=15.0)
    assert score_commit(commit, small_repo).score() > score_commit(commit, large_repo).score()


def test_baseline_from_empty_history_falls_back_to_defaults():
    base = Baseline.from_history(History(repo="x", commits=[]))
    assert base.median_churn == Baseline.default().median_churn


# -- the gate -------------------------------------------------------------


def _history(commits: list[Commit]) -> History:
    return History(repo="demo", commits=commits)


def test_all_source_commits_untested_blocks():
    h = _history([make(str(i), "x", [("src/a.py", 50, 0)]) for i in range(3)])
    result = evaluate(h)
    check = next(c for c in result.checks if c.name == "source changes without tests")
    assert check.status == BLOCK
    assert result.blocked
    assert result.verdict == "NO-GO"


def test_well_tested_small_release_passes():
    h = _history(
        [make(str(i), "x", [("src/a.py", 10, 2), ("tests/test_a.py", 8, 0)]) for i in range(4)]
    )
    result = evaluate(h)
    assert not result.blocked
    assert result.verdict in ("GO", "GO WITH WARNINGS")


def test_an_empty_range_is_blocked_rather_than_passed():
    """Nothing to release must not read as a clean bill of health."""
    result = evaluate(_history([]))
    assert result.blocked


def test_every_check_reports_what_it_saw():
    h = _history([make("a", "x", [("src/a.py", 10, 0), ("tests/t.py", 1, 0)])])
    for check in evaluate(h).checks:
        assert check.detail
        assert check.status in (PASS, WARN, BLOCK)


def test_strictness_is_relative_to_the_repo_median():
    """A 3000-line commit is an outlier only where commits are usually small."""
    normal = [make(str(i), "x", [("src/a.py", 20, 0), ("tests/t.py", 2, 0)]) for i in range(6)]
    spike = make("big", "huge", [("src/a.py", 3000, 0), ("tests/t.py", 5, 0)])
    result = evaluate(_history([spike, *normal]))
    outlier = next(c for c in result.checks if "median" in c.name)
    assert outlier.status == WARN


# -- ranking comparison ---------------------------------------------------


def test_rank_disagreement_is_empty_for_a_single_commit():
    assert rank_disagreement(_history([make("a", "x", [("a.py", 1, 0)])])) == {}


def test_rank_by_risk_differs_from_rank_by_churn_on_a_dump():
    dump = make("dump", "results", [("results/r.json", 50000, 0)])
    broad = make("broad", "refactor", [(f"src/a{i}/m.py", 20, 20) for i in range(8)])
    h = _history([dump, broad])
    assert rank_by(h, "churn")[0].sha == "dump"
    assert rank_by(h, "risk")[0].sha == "broad"


# -- a check that measured nothing ----------------------------------------


def test_a_docs_only_release_does_not_clear_the_test_coupling_check():
    """It used to come back PASS, with the detail "no source changes".

    `captain sweep <folder> --since 8` over 75 local checkouts returned 19 clean GO
    verdicts on 2026-10-06, and 6 of those 19 are this case - releases of documentation
    and data,
    where "no source shipped untested" is true only because no source shipped. The
    gate printed the same "ok" it prints for a release whose every source file
    arrived with a test.
    """
    docs = make("d", "rewrite the install section", [("README.md", 40, 12)])
    result = evaluate(_history([docs]))

    coupling = next(c for c in result.checks if "without tests" in c.name)
    assert coupling.status == NOT_MEASURED
    assert coupling.status != PASS
    assert result.verdict == "GO"  # nothing observed is not a failure
    assert result.not_measured == [coupling]
    assert result.evidence == "3 of 4 checks measured something"


def test_the_report_says_how_many_checks_measured_something():
    """So a reader can weigh the verdict without re-deriving it."""
    report = render(evaluate(_history([make("d", "docs", [("README.md", 5, 0)])])))
    assert "3 of 4 checks measured something" in report
    assert " -  " in report  # the status column, not "ok"
    assert "ok   source changes without tests" not in report


def test_a_release_that_touches_source_measures_every_check():
    both = make(
        "s", "parser and its tests", [("src/pkg/parse.py", 80, 3), ("tests/t.py", 40, 0)]
    )
    result = evaluate(_history([both]))
    assert result.not_measured == []
    assert result.evidence == "4 of 4 checks measured something"


def test_the_outlier_threshold_is_a_multiple_of_the_repositorys_own_median():
    """The rule behind the three thresholds the README quotes: 20x the median.

    Written once with the wrong arithmetic twice over: 400 lines against a 114-line
    median is 3.5x, and against a 20-line median it is exactly 20x, which the check
    does not fire on because the comparison is strict. The rule is asserted here
    rather than described.
    """
    tiny = [make(str(i), "x", [("src/a.py", 20, 0)]) for i in range(7)]
    large = [make(str(i), "x", [("src/a.py", 2100, 0)]) for i in range(7)]
    assert Baseline.from_history(_history(tiny)).median_churn == 20
    assert Baseline.from_history(_history(large)).median_churn == 2100

    # 500 lines: past 20x the 20-line median, a fraction of the 2,100-line one.
    five_hundred = make("f", "x", [("src/a.py", 500, 0)])
    for history, fires in (
        (_history([five_hundred, *tiny]), True),
        (_history([five_hundred, *large]), False),
    ):
        check = next(c for c in evaluate(history).checks if "median" in c.name)
        assert (check.status == WARN) is fires
        assert ("20x" in check.detail) is fires


def test_the_outlier_comparison_is_strict_at_exactly_twenty_times():
    """Exactly 20x does not fire. Worth pinning because a README sentence assumed it did."""
    tiny = [make(str(i), "x", [("src/a.py", 20, 0)]) for i in range(7)]
    for churn, fires in ((400, False), (401, True)):
        at = make("f", "x", [("src/a.py", churn, 0)])
        check = next(c for c in evaluate(_history([at, *tiny])).checks if "median" in c.name)
        assert (check.status == WARN) is fires, churn


# -- the README's agreement table, against its own arithmetic ------------


def test_the_readme_quotes_the_pairs_the_command_prints():
    """Three numbers and three labels were wrong at once.

    The table read "lines vs files +25%", "lines vs spread +21%", "files vs spread
    +32%" over 28 repositories. `captain compare` prints "churn vs files +41%",
    "churn vs spread +33%", "files vs spread +42%" over 63 — so every figure had
    drifted and the metric was not even called by the name the tool uses.

    Re-measuring 63 checkouts here would take minutes and depend on what is on the
    machine, so this checks the two things that cannot be true by accident: the pair
    names match the ones `rank_disagreement` returns, and the figures in the README
    are the ones the module's own labels go with.
    """
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    quoted = dict(re.findall(r"\| (\w+ vs \w+) \| \*\*\+(\d+)%\*\* \|", readme))
    assert quoted, "the agreement table no longer parses"

    # Two commits, because `rank_disagreement` returns {} for fewer than two - which is
    # what the substituted set was papering over.
    produced = set(
        rank_disagreement(
            _history(
                [
                    make("a", "x", [("src/a.py", 10, 0)]),
                    make("b", "y", [("src/b.py", 1, 0), ("docs/c.md", 1, 0)]),
                ]
            ),
            top=2,
        )
    )
    # `if not produced: produced = {...}` was here, so when the call returned nothing
    # the test asserted the README against a set the test itself had just supplied. A
    # one-commit history does produce pairs; if it ever stops, that is a finding and not
    # something to substitute around.
    assert produced, "rank_disagreement returned no pairs, so this test has nothing to check"
    assert set(quoted) == produced, (
        f"the README names {sorted(quoted)}; the command produces {sorted(produced)}"
    )
    # And the VALUES, recomputed. This checked only the keys, so "+41%" could become
    # "+99%" with the test green - and the three figures had in fact drifted to
    # +42/+33/+41 while the README still said +41/+33/+42.
    measured = _measured_agreement()
    if measured is None:
        pytest.skip("no folder of checkouts here; REPOS_ROOT names one")
    for pair, stated in quoted.items():
        assert pair in measured, (pair, sorted(measured))
        assert int(stated) == measured[pair], (
            f"the README says {pair} +{stated}%; `captain compare` measures +{measured[pair]}%"
        )


def _measured_agreement() -> dict[str, int] | None:
    """`captain compare`'s three figures over the folder of checkouts, or None.

    Over the live folder, so it moves when anyone commits - which is why the README
    carries a measurement date beside the table. What this catches is the drift the
    key-only check could not see at all.
    """
    import os
    import re
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    folder = Path(os.environ.get("REPOS_ROOT") or root.parents[2])
    if not folder.is_dir() or len(list(folder.glob("*/.git"))) < 10:
        return None
    done = subprocess.run(
        [sys.executable, "-m", "captain.cli", "compare", str(folder)],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=900,
    )
    if done.returncode != 0:
        return None
    found = re.findall(r"(\w+ vs \w+)\s+mean excess over chance = \+(\d+)%", done.stdout)
    return {pair: int(value) for pair, value in found} or None


# -- the headline, which no command computed ----------------------------------


def test_the_extremes_headline_is_the_one_the_command_prints():
    """The README's first sentence had no producer.

    `gate`, `explain`, `rank`, `sweep` and `compare` are all per-repository, so nothing
    computed a maximum across the folder - and the quoted figure was wrong in both
    halves: 196,743 lines in 11 files, where the real maximum is 215,924 across 240.
    The 11 was what made the breadth ratio read 164x; against the real commit it is 8x.

    Driven on a constructed pair of repositories rather than the live folder, because
    the live figures move when anyone commits. What is checked against the live folder
    is only that the command runs and reports the same repository count the README
    states.
    """
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "captain extremes" in readme, "the README no longer names the command"
    stated = re.search(
        r"changed the most lines changed\s+([\d,]+) of them across ([\d,]+) files",
        readme.replace(chr(10), " "),
    )
    assert stated, "the headline no longer states the maximum by lines"
    lines, files = (int(g.replace(",", "")) for g in stated.groups())
    # The old pair, pinned as gone. 11 files beside a six-figure churn is the shape of
    # the error - a commit that large touching eleven files is not a plausible maximum.
    assert (lines, files) != (196743, 11), "the figure with no producer is back"
    assert files > 100, f"{files} files beside {lines:,} lines is the old mistake"

    ratio = re.search(r"the first is (\d+) times the second", readme)
    assert ratio, "the headline no longer states the ratio"
    second = re.search(r"changed 510\s+lines across ([\d,]+)", readme.replace(chr(10), " "))
    assert second, "the headline no longer states the maximum by files"
    assert int(ratio.group(1)) == round(lines / 510), (ratio.group(1), lines)


def test_the_metric_names_in_the_readme_are_the_ones_the_code_uses():
    """ "lines" appears nowhere in the pair labels; the field is `churn`."""
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("| Pair |") : readme.index("The metrics *agree*")]
    assert "lines vs" not in table, "the table calls churn 'lines' again"
    assert "churn vs files" in table
    assert "churn vs spread" in table


def test_the_rank_pairs_are_exactly_three():
    """So a fourth metric cannot appear without the README table changing."""
    commits = [make(str(i), "x", [(f"src/a{i}.py", 10 * i, 0)]) for i in range(1, 7)]
    pairs = rank_disagreement(_history(commits), top=3)
    assert set(pairs) == {"churn vs files", "churn vs spread", "files vs spread"}


# -- a path argument that is wrong in the ordinary ways -----------------------


def test_a_folder_command_given_a_file_says_so(tmp_path, capsys):
    """`NotADirectoryError` out of `main()` for the commonest mistake there is.

    `sweep`, `compare` and `extremes` all take a folder of checkouts and all did
    `Path(raw).resolve()` then `iterdir()`. Giving a file - or a path that is not there
    at all - produced a stack trace naming this module's `iterdir`, which is not what
    the reader got wrong.
    """
    from captain.cli import main

    a_file = tmp_path / "notes.txt"
    a_file.write_text("x", encoding="utf-8")

    for command in ("sweep", "compare", "extremes"):
        assert main([command, str(a_file)]) == 2, command
        err = capsys.readouterr().err
        assert "is a file" in err, (command, err)
        assert "Traceback" not in err


def test_a_folder_command_given_a_missing_path_says_so(tmp_path, capsys):
    from captain.cli import main

    for command in ("sweep", "compare", "extremes"):
        assert main([command, str(tmp_path / "nope")]) == 2, command
        assert "no such path" in capsys.readouterr().err, command


def test_every_subcommand_answers_a_non_repository_the_same_way(tmp_path, capsys):
    """`gate` caught `NotAGitRepository` and returned 2; `rank`, `explain` and
    `extremes` did not, so the same mistake was a readable message from one subcommand
    and a stack trace from the next."""
    from captain.cli import main

    for argv in (
        ["gate", str(tmp_path)],
        ["rank", str(tmp_path), "--by", "churn"],
        ["explain", str(tmp_path), "HEAD"],
    ):
        assert main(argv) == 2, argv
        err = capsys.readouterr().err
        assert err.strip(), argv
        assert "Traceback" not in err


def test_extremes_refuses_a_folder_with_no_history(tmp_path, capsys):
    """Exit 2 rather than printing a maximum over nothing."""
    from captain.cli import main

    (tmp_path / "empty").mkdir()
    assert main(["extremes", str(tmp_path)]) == 2
    assert "no checkout" in capsys.readouterr().err
