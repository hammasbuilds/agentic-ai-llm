"""Scheduler tests.

The properties asserted here are the ones a learner would notice: intervals
grow, a lapse costs something but not everything, and the same inputs always
produce the same schedule.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tutor.scheduler import (
    AGAIN,
    EASY,
    GOOD,
    HARD,
    Card,
    CardState,
    _interval_for,
    due_cards,
    fsrs,
    sm2,
)
from tutor.simulate import lapse_recovery, simulate

TODAY = date(2026, 1, 1)


def establish(fn, reviews: int = 6) -> CardState:
    state, day = CardState(), TODAY
    for _ in range(reviews):
        state = fn(state, GOOD, day)
        day = state.due
    return state


# -- both schedulers -------------------------------------------------------


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_intervals_grow_with_successful_reviews(fn):
    state, day, seen = CardState(), TODAY, []
    for _ in range(5):
        state = fn(state, GOOD, day)
        seen.append(state.interval)
        day = state.due
    assert seen == sorted(seen)
    assert seen[-1] > seen[0]


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_easy_schedules_further_out_than_hard(fn):
    base = establish(fn, 3)
    assert fn(base, EASY, TODAY).interval >= fn(base, HARD, TODAY).interval


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_a_lapse_shortens_the_interval(fn):
    base = establish(fn)
    assert fn(base, AGAIN, TODAY).interval < base.interval


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_scheduling_is_deterministic(fn):
    """An LLM would not give the same answer twice. That is the argument."""
    base = establish(fn, 4)
    assert fn(base, GOOD, TODAY) == fn(base, GOOD, TODAY)


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_due_date_matches_the_interval(fn):
    state = fn(CardState(), GOOD, TODAY)
    assert state.due == TODAY + timedelta(days=state.interval)


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_an_invalid_grade_is_refused(fn):
    with pytest.raises(ValueError, match="grade must be"):
        fn(CardState(), 7, TODAY)


@pytest.mark.parametrize("fn", [sm2, fsrs])
def test_intervals_are_never_shorter_than_a_day(fn):
    state = CardState()
    for grade in (AGAIN, HARD, AGAIN, GOOD, AGAIN):
        state = fn(state, grade, TODAY)
        assert state.interval >= 1


# -- the difference that matters ------------------------------------------


def test_sm2_discards_the_whole_history_on_one_lapse():
    """SM-2 restarts at one day regardless of how well established the card was."""
    assert lapse_recovery("sm2")[0] == 1


def test_fsrs_keeps_most_of_the_stability_through_a_lapse():
    fsrs_first = lapse_recovery("fsrs")[0]
    assert fsrs_first > 10
    assert fsrs_first > lapse_recovery("sm2")[0] * 10


def test_a_lapse_reduces_stability_rather_than_deleting_it():
    base = establish(fsrs)
    after = fsrs(base, AGAIN, TODAY)
    assert 0 < after.stability < base.stability


def test_sm2_ease_has_a_floor():
    """Repeated lapses must not drive the multiplier to zero."""
    state = CardState()
    for _ in range(30):
        state = sm2(state, AGAIN, TODAY)
    assert state.ease >= 1.3


def test_fsrs_difficulty_stays_in_range():
    state = CardState()
    for grade in (AGAIN, AGAIN, EASY, EASY, HARD, GOOD) * 5:
        state = fsrs(state, grade, TODAY)
        assert 1.0 <= state.difficulty <= 10.0


# -- the memory model ------------------------------------------------------


def test_recall_probability_decays_with_time():
    state = CardState(stability=10.0)
    assert state.recall_probability(0) == 1.0
    assert state.recall_probability(10) > state.recall_probability(100)


def test_the_interval_targets_the_desired_retention():
    """At the scheduled interval, recall should sit at the target, not above."""
    stability = 20.0
    interval = _interval_for(stability, retention=0.9)
    probability = CardState(stability=stability).recall_probability(interval)
    assert probability == pytest.approx(0.9, abs=0.02)


def test_an_unseen_card_has_no_recall():
    assert CardState().recall_probability(1) == 0.0


# -- decks -----------------------------------------------------------------


def test_due_cards_are_ordered_most_overdue_first():
    a = Card("a", "1", CardState(due=TODAY - timedelta(days=5)))
    b = Card("b", "2", CardState(due=TODAY - timedelta(days=1)))
    c = Card("c", "3", CardState(due=TODAY + timedelta(days=5)))
    assert [card.question for card in due_cards([b, c, a], TODAY)] == ["a", "b"]


def test_a_new_card_is_always_due():
    assert due_cards([Card("q", "a")], TODAY)


def test_review_records_history():
    card = Card("q", "a").review(GOOD, TODAY)
    assert card.history == [(TODAY, GOOD)]


# -- simulation ------------------------------------------------------------


def test_the_simulation_is_reproducible():
    first = simulate("fsrs", days=60, cards=5, seed=3)
    second = simulate("fsrs", days=60, cards=5, seed=3)
    assert (first.reviews, first.lapses) == (second.reviews, second.lapses)


def test_a_different_seed_gives_a_different_run():
    assert (
        simulate("fsrs", days=60, cards=5, seed=1).reviews
        != simulate("fsrs", days=60, cards=5, seed=99).reviews
    )


def test_recall_at_review_lands_near_the_target():
    """If the scheduler works, cards are tested when recall is around 90%."""
    outcome = simulate("fsrs", days=365, cards=30, seed=5)
    assert 0.6 < outcome.mean_recall < 0.95


# -- a deck path that is wrong in the four ordinary ways -----------------------


def _run(argv, capsys):
    from tutor.cli import main

    code = main(argv)
    return code, capsys.readouterr()


@pytest.mark.parametrize(
    "contents,expect",
    [
        ("", "is empty"),
        ("   \n", "is empty"),
        ("not json at all", "not valid JSON"),
        ('{"a": 1}', "holds a dict"),
        ("[1, 2, 3]", "card 1 is a int"),
        ('[{"answer": "a"}]', "card 1 has no 'question'"),
        ('[{"question": "q"}]', "card 1 has no 'answer'"),
        ('[{"question": "q", "answer": "a", "state": 5}]', "non-object 'state'"),
        ('[{"question": "q", "answer": "a", "state": {"due": "yesterday"}}]', "YYYY-MM-DD"),
        ('[{"question": "q", "answer": "a", "state": {"due": 7}}]', "YYYY-MM-DD"),
    ],
    ids=lambda v: str(v)[:34],
)
def test_a_malformed_deck_is_one_line_and_exit_two(contents, expect, tmp_path, capsys):
    """Every one of these was a traceback out of `main()`.

    `study-tutor due <deck>` is the first command the README gives. An unreadable deck
    gave `JSONDecodeError`, a missing one `FileNotFoundError`, a locked one
    `PermissionError`, and an empty file the first of those - four stack traces for the
    four ordinary ways a path argument goes wrong, each pointing at this program's
    `json.loads` rather than at what the reader got wrong.
    """
    deck = tmp_path / "deck.json"
    deck.write_text(contents, encoding="utf-8")

    code, out = _run(["due", str(deck)], capsys)
    assert code == 2, out.out + out.err
    assert expect in out.err, out.err
    assert "Traceback" not in out.err


def test_a_missing_deck_says_so(tmp_path, capsys):
    code, out = _run(["due", str(tmp_path / "nope.json")], capsys)
    assert code == 2
    assert "no deck at" in out.err


def test_a_directory_given_as_a_deck_says_so(tmp_path, capsys):
    code, out = _run(["due", str(tmp_path)], capsys)
    assert code == 2
    assert "is a directory" in out.err


def test_a_deck_that_is_not_utf8_says_so(tmp_path, capsys):
    deck = tmp_path / "deck.json"
    deck.write_bytes(b"\xff\xfe[]")
    code, out = _run(["due", str(deck)], capsys)
    assert code == 2
    assert "not UTF-8" in out.err


def test_an_empty_deck_still_works(tmp_path, capsys):
    """A refusal that refuses everything is not validation. `[]` is a valid deck."""
    deck = tmp_path / "deck.json"
    deck.write_text("[]", encoding="utf-8")
    code, _ = _run(["due", str(deck)], capsys)
    assert code == 0


def test_a_real_deck_still_works(tmp_path, capsys):
    deck = tmp_path / "deck.json"
    deck.write_text(
        '[{"question": "q", "answer": "a", "state": {"due": "2020-01-01", "reps": 2}}]',
        encoding="utf-8",
    )
    code, out = _run(["due", str(deck)], capsys)
    assert code == 0, out.err
    assert "q" in out.out
