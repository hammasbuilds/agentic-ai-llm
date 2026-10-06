"""The `compare` command's output, which is what the README's table is.

`compare` is the only command that reads a whole folder of checkouts, so it is the one
whose numbers end up quoted. It printed `repo-calls` as a bare percentage.
"""

from __future__ import annotations

from cartographer.cli import main

# -- a rate with no denominator beside it ------------------------------------


def test_compare_prints_the_internal_call_count_per_repository(tmp_path, capsys):
    """`repo-calls` was printed as a percentage alone.

    So a checkout with nine internal call sites and one with nine thousand produced the
    same `100%`, and in a folder of real repositories the tiny ones score highest for
    having almost nothing to resolve. The `n` column is that denominator, and the pooled
    fraction under the table is the reading the median cannot give: across the surveyed
    folder they differ by six points.
    """
    tiny = tmp_path / "tiny"
    tiny.mkdir()
    (tiny / "m.py").write_text(
        "def a():\n    return 1\n\n\ndef b():\n    return a()\n", "utf-8"
    )

    assert main(["compare", str(tmp_path)]) == 0
    out = capsys.readouterr().out

    header = next(ln for ln in out.splitlines() if ln.startswith("repo "))
    assert header.split()[-4:] == ["repo-calls", "n", "core", "module"], header
    row = next(ln for ln in out.splitlines() if ln.startswith("tiny"))
    # One internal call site: a() inside b(). The rate is 100% and that is the point.
    assert row.split()[-2] == "1", row
    assert "100%" in row, row
    assert "pooled over every call site: 1 of 1 resolved (100%)" in out, out
    assert "1 of 1 repositories have fewer than 50 internal call sites" in out, out


def test_compare_pools_rather_than_dividing_by_zero(tmp_path, capsys):
    """A folder whose repositories have no internal calls at all."""
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "m.py").write_text("import json\n\nx = json.dumps({})\n", encoding="utf-8")

    assert main(["compare", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no repo-internal call sites to pool" in out, out
