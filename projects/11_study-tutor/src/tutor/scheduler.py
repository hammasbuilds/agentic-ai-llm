"""Spaced-repetition scheduling. Deterministic, and deliberately not a model's job.

Two schedulers are implemented so they can be compared on the same review
history: SM-2, the 1987 algorithm most flashcard apps still use, and FSRS, the
memory model that replaced it.

The reason this module exists at all is the project's rule: **an LLM must never
choose a review interval.** Interval choice is arithmetic over a memory model,
it is reproducible, and it is testable. A model asked "when should I review
this?" produces a plausible number with no memory model behind it and no way to
check it. The model's job here is writing the questions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

# Grades, as the user gives them.
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
GRADES = (AGAIN, HARD, GOOD, EASY)


@dataclass(frozen=True)
class CardState:
    """What is known about one card's memory trace."""

    stability: float = 0.0  # days until recall probability falls to 0.9
    difficulty: float = 5.0  # 1..10, intrinsic to the item
    interval: int = 0  # days until the next review
    reps: int = 0
    lapses: int = 0
    ease: float = 2.5  # SM-2 only
    due: date | None = None

    def recall_probability(self, elapsed_days: float) -> float:
        """Chance of recalling this card after `elapsed_days`.

        The forgetting curve, not a guess. With stability s, recall decays as
        (1 + t/(9s))^-1, which is the FSRS formulation.
        """
        if self.stability <= 0:
            return 0.0
        return (1 + elapsed_days / (9 * self.stability)) ** -1


# -- SM-2 -----------------------------------------------------------------


def sm2(state: CardState, grade: int, today: date) -> CardState:
    """SuperMemo-2, as published. Kept honest rather than improved."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}, got {grade}")

    if grade == AGAIN:
        # SM-2 resets the interval entirely on a lapse. This is the behaviour
        # the comparison in the README is about.
        return replace(
            state,
            interval=1,
            reps=0,
            lapses=state.lapses + 1,
            ease=max(1.3, state.ease - 0.2),
            due=today + timedelta(days=1),
        )

    quality = {HARD: 3, GOOD: 4, EASY: 5}[grade]
    ease = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(1.3, ease)

    reps = state.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = max(1, round(state.interval * ease))

    return replace(
        state, interval=interval, reps=reps, ease=ease, due=today + timedelta(days=interval)
    )


# -- FSRS -----------------------------------------------------------------

# Published default weights for FSRS-4.5. Not tuned here: tuning them without
# a real review log would be inventing a memory model.
W = (
    0.4872,
    1.4003,
    3.7145,
    13.8206,
    5.1618,
    1.2298,
    0.8975,
    0.031,
    1.6474,
    0.1367,
    1.0461,
    2.1072,
    0.0793,
    0.3246,
    1.587,
    0.2272,
    2.8755,
)

DESIRED_RETENTION = 0.9


def _initial_stability(grade: int) -> float:
    return max(0.1, W[grade - 1])


def _initial_difficulty(grade: int) -> float:
    return min(10.0, max(1.0, W[4] - (grade - 3) * W[5]))


def _next_difficulty(difficulty: float, grade: int) -> float:
    delta = difficulty - W[6] * (grade - 3)
    # Mean reversion towards the difficulty of an "easy" first answer.
    reverted = W[7] * _initial_difficulty(EASY) + (1 - W[7]) * delta
    return min(10.0, max(1.0, reverted))


def _next_stability(state: CardState, grade: int, retrievability: float) -> float:
    if grade == AGAIN:
        # A lapse reduces stability; it does not delete it. This is the
        # difference that the comparison measures.
        return min(
            state.stability,
            W[11]
            * state.difficulty ** -W[12]
            * ((state.stability + 1) ** W[13] - 1)
            * math.exp((1 - retrievability) * W[14]),
        )

    hard_penalty = W[15] if grade == HARD else 1.0
    easy_bonus = W[16] if grade == EASY else 1.0
    return state.stability * (
        1
        + math.exp(W[8])
        * (11 - state.difficulty)
        * state.stability ** -W[9]
        * (math.exp((1 - retrievability) * W[10]) - 1)
        * hard_penalty
        * easy_bonus
    )


def _interval_for(stability: float, retention: float = DESIRED_RETENTION) -> int:
    """Days until recall probability reaches the target."""
    return max(1, round(9 * stability * (1 / retention - 1)))


def fsrs(
    state: CardState, grade: int, today: date, elapsed_days: float | None = None
) -> CardState:
    """FSRS-4.5 with published weights."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}, got {grade}")

    if state.reps == 0 or state.stability <= 0:
        stability = _initial_stability(grade)
        difficulty = _initial_difficulty(grade)
    else:
        if elapsed_days is None:
            elapsed_days = float(state.interval)
        retrievability = state.recall_probability(elapsed_days)
        difficulty = _next_difficulty(state.difficulty, grade)
        stability = _next_stability(state, grade, retrievability)

    interval = _interval_for(stability)
    return replace(
        state,
        stability=stability,
        difficulty=difficulty,
        interval=interval,
        reps=state.reps + 1,
        lapses=state.lapses + (1 if grade == AGAIN else 0),
        due=today + timedelta(days=interval),
    )


SCHEDULERS = {"sm2": sm2, "fsrs": fsrs}


@dataclass
class Card:
    """A question, its answer, and its memory state."""

    question: str
    answer: str
    state: CardState = field(default_factory=CardState)
    history: list[tuple[date, int]] = field(default_factory=list)

    def review(self, grade: int, today: date, scheduler: str = "fsrs") -> Card:
        fn = SCHEDULERS[scheduler]
        self.state = fn(self.state, grade, today)
        self.history.append((today, grade))
        return self


def due_cards(cards: list[Card], today: date) -> list[Card]:
    """Cards due on or before today, most overdue first."""
    due = [c for c in cards if c.state.due is None or c.state.due <= today]
    return sorted(due, key=lambda c: c.state.due or date.min)
