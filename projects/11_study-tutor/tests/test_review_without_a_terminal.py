"""`review` asks questions. Run without a terminal it lost the answers already given.

Two defects in one line. `input()` raises `EOFError` when stdin is closed - piped, run
from a script, or redirected from /dev/null - and unhandled the traceback was the whole
answer. Worse, the deck was written only after the last card, so every grade given
before the stop was discarded: a session interrupted nine cards into ten saved nothing.
"""

from __future__ import annotations

import io
import json

import pytest

from tutor.cli import main

DECK = [
    {"question": "q1", "answer": "a1"},
    {"question": "q2", "answer": "a2"},
]


@pytest.fixture
def deck(tmp_path):
    path = tmp_path / "deck.json"
    path.write_text(json.dumps(DECK), encoding="utf-8")
    return path


def test_no_terminal_is_reported_rather_than_raised(deck, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code = main(["review", str(deck)])
    captured = capsys.readouterr()
    assert code == 1
    assert "needs a terminal" in captured.out
    assert "unchanged" in captured.out
    # Nothing was graded, so nothing was written.
    assert json.loads(deck.read_text(encoding="utf-8")) == DECK


def test_the_grades_given_before_the_stop_are_saved(deck, monkeypatch, capsys):
    """One card revealed and graded, then stdin ends."""
    monkeypatch.setattr("sys.stdin", io.StringIO("\n3\n"))
    code = main(["review", str(deck)])
    captured = capsys.readouterr()
    assert code == 1
    assert "stopped after 1 of 2" in captured.out

    cards = json.loads(deck.read_text(encoding="utf-8"))
    assert cards[0].get("state", {}).get("reps") == 1, cards[0]
    # And the card never reached is untouched.
    assert cards[1].get("state", {}).get("reps") in (None, 0), cards[1]


def test_a_full_session_still_saves_and_returns_zero(deck, monkeypatch, capsys):
    """The other direction: the handler must not turn a complete run into a failure."""
    monkeypatch.setattr("sys.stdin", io.StringIO("\n3\n\n3\n"))
    code = main(["review", str(deck)])
    captured = capsys.readouterr()
    assert code == 0, captured.out
    assert "saved" in captured.out
    cards = json.loads(deck.read_text(encoding="utf-8"))
    assert all(card["state"]["reps"] == 1 for card in cards)
