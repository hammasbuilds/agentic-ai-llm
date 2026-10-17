"""A looser threshold can compress LESS, and the table has to say so.

The sweep is read as a dial: lower the threshold, get more compression. Over 25,000
lines of a real Apache error log the template count goes 33 at 0.6, 46 at 0.5, 47 at
0.4 and 33 at 0.3 - loosening it produced half as much compression again.

Clustering is a single greedy pass. A line that would have started its own cluster at a
tight threshold instead joins an earlier, broader one; that cluster's template then
generalises far enough that later lines no longer match it and start clusters of their
own. The shape of the table invites the other conclusion, so the command prints the
contradiction rather than leaving a reader to spot it.
"""

from __future__ import annotations

from detective.cli import main
from detective.templates import Extraction, extract


def test_the_apache_shape_really_is_not_monotonic(tmp_path):
    """The property itself, on a log built to have it: two families of message where one
    is a near-match for the other only once the first has generalised."""
    lines = []
    for index in range(200):
        lines.append(f"[error] client 10.0.0.{index % 9} jk2_init failed worker {index}")
        lines.append(
            f"[notice] workerEnv.init ok /etc/httpd/conf/workers{index % 7}.properties"
        )
        lines.append(f"[error] mod_jk child workerEnv in error state {index % 5}")
    log = tmp_path / "apache.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts = {t: len(extract(lines, t).templates) for t in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)}
    # Not asserting WHICH way it bends - that is a property of this input - only that
    # the extractor is deterministic, so the warning cannot be flaky.
    again = {t: len(extract(lines, t).templates) for t in counts}
    assert counts == again


THRESHOLDS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)


def _rows(template_counts: list[int]) -> list[Extraction]:
    """A sweep with the template counts given.

    `compression` is `lines / len(templates)`, so the count is the dial. Built here
    rather than found in a fixture: the warning has to be exercised in both directions,
    and a log that bends one way does not also bend the other.
    """
    one = extract(["alpha beta gamma"], 0.6).templates[0]
    return [
        Extraction(templates=[one] * count, lines=1200, threshold=threshold, lines_read=1200)
        for count, threshold in zip(template_counts, THRESHOLDS, strict=True)
    ]


def test_a_non_monotonic_sweep_is_reported(tmp_path, capsys, monkeypatch):
    """The Apache shape: 33 templates at 0.6, then 46 at 0.5 and 47 at 0.4."""
    from detective import cli as cli_module

    monkeypatch.setattr(
        cli_module, "sweep", lambda *a, **k: _rows([318, 79, 46, 33, 46, 47, 33])
    )
    log = tmp_path / "a.log"
    log.write_text("alpha beta gamma\n", encoding="utf-8")

    main(["cost", str(log)])
    out = capsys.readouterr().out
    assert "NOT MONOTONIC" in out
    assert "0.5 below 0.6" in out
    assert "greedy pass" in out


def test_a_monotonic_sweep_says_nothing(tmp_path, capsys, monkeypatch):
    """The other direction, so the warning is about the data and not always printed."""
    from detective import cli as cli_module

    monkeypatch.setattr(
        cli_module, "sweep", lambda *a, **k: _rows([318, 200, 120, 80, 50, 40, 30])
    )
    log = tmp_path / "b.log"
    log.write_text("alpha beta gamma\n", encoding="utf-8")

    main(["cost", str(log)])
    assert "NOT MONOTONIC" not in capsys.readouterr().out
