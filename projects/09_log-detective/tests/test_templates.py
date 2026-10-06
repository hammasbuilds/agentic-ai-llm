"""Template extraction tests, and the loss accounting that is the point."""

from __future__ import annotations

import pytest

from detective.templates import extract, mask, sweep, tokenise

# -- masking ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("2026-09-17T12:00:00", "<TIME>"),
        ("2026-09-17", "<DATE>"),
        ("12:00:00.123", "<TIME>"),
        ("42", "<NUM>"),
        ("-3.5", "<NUM>"),
        ("1e6", "<NUM>"),
        ("97%", "<PCT>"),
        ("/var/log/app", "<PATH>"),
        ("C:\\Users\\x", "<PATH>"),
        ("https://example.com/a", "<URL>"),
        ("10.0.0.1:8080", "<IP>"),
        ("deadbeefcafe", "<HASH>"),
        ("4f3a2b1c-1111-2222-3333-444455556666", "<UUID>"),
        ("module.py", "<FILE>"),
        ("PASSED", "PASSED"),
        ("error", "error"),
    ],
)
def test_variable_tokens_are_masked(token: str, expected: str):
    assert mask(token) == expected


def test_words_survive_masking():
    assert tokenise("connection refused after 3 retries") == [
        "connection",
        "refused",
        "after",
        "<NUM>",
        "retries",
    ]


# -- grouping --------------------------------------------------------------


def test_identical_lines_collapse_to_one_template():
    result = extract(["user alice logged in"] * 5)
    assert len(result.templates) == 1
    assert result.templates[0].count == 5


def test_lines_differing_only_in_a_number_share_a_template():
    result = extract(["request took 3 ms", "request took 91 ms"])
    assert len(result.templates) == 1
    assert result.templates[0].distinct_messages == 1  # identical after masking


def test_lines_of_different_length_never_merge():
    """Two lines of different token count are never the same event."""
    result = extract(["a b c", "a b c d e"], threshold=0.0)
    assert len(result.templates) == 2


def test_dissimilar_lines_stay_separate_at_a_tight_threshold():
    result = extract(["disk full on node one", "user alice has logged out"], threshold=0.9)
    assert len(result.templates) == 2


def test_a_loose_threshold_merges_them_and_says_so():
    """The merge is allowed; hiding it is not.

    The lines must share at least one token for any threshold above zero to
    merge them - two lines with nothing in common score 0.0 similarity and
    stay apart however loose the threshold, which is correct and is why an
    earlier version of this test failed.
    """
    result = extract(["disk full on node one", "disk alice has logged out"], threshold=0.1)
    assert len(result.templates) == 1
    template = result.templates[0]
    assert template.merged
    assert template.distinct_messages == 2
    assert template.wildcards >= 4


def test_lines_with_nothing_in_common_never_merge():
    """Similarity 0.0 fails every threshold above zero, by construction."""
    result = extract(["disk full on node one", "user alice has logged out"], threshold=0.1)
    assert len(result.templates) == 2


# -- loss accounting -------------------------------------------------------


def test_a_merged_template_keeps_its_members():
    result = extract(["error opening file", "error closing file"], threshold=0.5)
    template = result.templates[0]
    assert template.distinct_messages == 2
    assert len(template.examples()) == 2


def test_distinct_messages_lost_counts_the_damage():
    result = extract(["alpha one two", "beta one two", "gamma one two"], threshold=0.5)
    assert len(result.templates) == 1
    assert result.distinct_messages_lost == 2


def test_nothing_is_lost_when_nothing_merges():
    result = extract(["alpha one two", "beta three four"], threshold=0.95)
    assert result.distinct_messages_lost == 0
    assert result.merged_templates == []


def test_compression_and_loss_move_together():
    """The finding, as an assertion: looser thresholds cost distinctions."""
    lines = [f"task {i} finished with code {i % 3}" for i in range(40)]
    lines += [f"unexpected {word} during shutdown" for word in ("panic", "stall", "abort")]
    tight = extract(lines, threshold=0.95)
    loose = extract(lines, threshold=0.3)
    assert loose.compression > tight.compression
    assert loose.distinct_messages_lost >= tight.distinct_messages_lost


def test_sweep_covers_every_threshold():
    lines = ["a b c d", "a b c e", "x y z w"]
    results = sweep(lines, thresholds=(0.9, 0.5))
    assert [r.threshold for r in results] == [0.9, 0.5]


# -- the rare line ---------------------------------------------------------


def test_a_rare_line_survives_at_a_tight_threshold():
    lines = ["heartbeat ok"] * 200 + ["kernel panic in driver"]
    result = extract(lines, threshold=0.9)
    assert any("panic" in t.text for t in result.singletons)


def test_the_same_rare_line_is_absorbed_at_a_loose_one():
    """The line you opened the log for is the one compression eats."""
    lines = ["heartbeat ok now"] * 200 + ["kernel panic now"]
    tight = extract(lines, threshold=0.9)
    loose = extract(lines, threshold=0.2)
    assert len(tight.templates) > len(loose.templates)
    assert loose.distinct_messages_lost > tight.distinct_messages_lost


def test_rarest_is_ordered_by_frequency():
    lines = ["common line here"] * 10 + ["rare line here"]
    counts = [t.count for t in extract(lines, threshold=0.9).rarest(2)]
    assert counts == sorted(counts)


# -- robustness ------------------------------------------------------------


def test_blank_lines_are_ignored():
    assert extract(["", "   ", "real line here"]).lines == 1


def test_an_empty_log_does_not_divide_by_zero():
    result = extract([])
    assert result.templates == []
    assert result.compression == 0.0


def test_first_line_number_is_recorded():
    result = extract(["alpha", "beta"], threshold=0.9)
    assert {t.first_line for t in result.templates} == {1, 2}


def test_line_counts_add_up():
    lines = [f"job {i} done" for i in range(25)] + ["something else entirely here"]
    result = extract(lines, threshold=0.6)
    assert sum(t.count for t in result.templates) == result.lines == 26


# -- one input, one corpus size -------------------------------------------


def test_both_commands_agree_on_how_many_lines_they_read(tmp_path, capsys):
    """They did not. `cost` printed the lines read; every ratio divided by the lines
    scored, because `extract` skips blanks. One input gave 1,005 under the header and
    973 in the arithmetic, and the README and the badge both took the larger.
    """
    from detective.cli import main

    log = tmp_path / "sample.log"
    log.write_text(
        chr(10).join(["alpha 1 started", "", "alpha 2 started", "   ", "beta done"]) + chr(10),
        encoding="utf-8",
    )

    assert main(["cost", str(log)]) == 0
    cost = capsys.readouterr().out
    assert "5 lines read, 3 scored (2 blank)" in cost
    assert "every ratio below is over the scored count" in cost

    assert main(["templates", str(log)]) == 0
    templates = capsys.readouterr().out
    assert templates.startswith("3 lines ->"), templates.splitlines()[0]
    assert "2 blank and not scored" in templates


def test_a_file_with_no_blank_lines_says_so(tmp_path, capsys):
    from detective.cli import main

    log = tmp_path / "dense.log"
    log.write_text("one a" + chr(10) + "one b" + chr(10), encoding="utf-8")
    assert main(["cost", str(log)]) == 0
    assert "2 lines, none blank" in capsys.readouterr().out


def test_the_extraction_reports_both_counts():
    from detective.templates import extract

    result = extract(["alpha one", "", "alpha two", "  "])
    assert result.lines == 2, "blank lines are not events"
    assert result.lines_read == 4
    assert result.blank_lines == 2
    assert result.compression == result.lines / len(result.templates)


def test_the_readme_quotes_the_scored_count_as_the_denominator():
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    stated = re.search(
        r"([\d,]+) lines read, ([\d,]+) scored "
        + chr(92)
        + r"(([\d,]+) blank"
        + chr(92)
        + r")",
        readme,
    )
    assert stated, "the README no longer prints the two counts"
    read, scored, blank = (int(g.replace(",", "")) for g in stated.groups())
    assert read == scored + blank
    assert f"{scored}" in readme.split('alt="lines"')[0], (
        "the badge should quote the scored count"
    )
