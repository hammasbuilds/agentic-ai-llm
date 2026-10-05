"""Simulate a learner and compare schedulers on identical review histories.

The learner is a forgetting curve, not a person. That is stated plainly rather
than dressed up: this measures how two scheduling algorithms behave against a
stated memory model, which is what a scheduler comparison can honestly measure
without a real review log.

The model is the same one FSRS optimises against, so the comparison is not
neutral - it is a check that each scheduler does what it claims under the
assumptions it was designed for, and a measurement of what that costs the
learner in reviews.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from .scheduler import AGAIN, EASY, GOOD, HARD, SCHEDULERS, Card, CardState


@dataclass
class Outcome:
    scheduler: str
    days: int
    reviews: int
    lapses: int
    final_recall: float  # probability of recall at the end of the run
    recall_samples: list[float]

    @property
    def reviews_per_day(self) -> float:
        return self.reviews / self.days if self.days else 0.0

    @property
    def mean_recall(self) -> float:
        return (
            sum(self.recall_samples) / len(self.recall_samples) if self.recall_samples else 0.0
        )


def _true_recall(true_stability: float, elapsed: float) -> float:
    if true_stability <= 0:
        return 0.0
    return (1 + elapsed / (9 * true_stability)) ** -1


def simulate(
    scheduler: str,
    days: int = 365,
    cards: int = 50,
    seed: int = 7,
    item_difficulty: float = 1.0,
) -> Outcome:
    """Run one scheduler over a simulated year.

    `item_difficulty` scales how fast the learner's true memory decays; 1.0 is
    an ordinary item, 0.5 a hard one.
    """
    rng = random.Random(seed)
    fn = SCHEDULERS[scheduler]
    start = date(2026, 1, 1)

    deck = [Card(question=f"q{i}", answer=f"a{i}") for i in range(cards)]
    # The learner's real memory, hidden from the scheduler.
    true_stability = [0.0] * cards
    last_seen = [start] * cards

    reviews = 0
    lapses = 0
    samples: list[float] = []

    for day_offset in range(days):
        today = start + timedelta(days=day_offset)
        for index, card in enumerate(deck):
            if card.state.due is not None and card.state.due > today:
                continue

            elapsed = (today - last_seen[index]).days
            probability = _true_recall(true_stability[index], elapsed)
            samples.append(probability)
            recalled = rng.random() < probability

            if not recalled:
                grade = AGAIN
                lapses += 1
                true_stability[index] = max(0.4, true_stability[index] * 0.4)
            else:
                grade = rng.choices([HARD, GOOD, EASY], weights=[2, 6, 2])[0]
                growth = {HARD: 1.3, GOOD: 2.0, EASY: 3.0}[grade]
                base = true_stability[index] or 1.0
                true_stability[index] = base * growth * item_difficulty

            card.state = fn(card.state, grade, today)
            last_seen[index] = today
            reviews += 1

    final = [
        _true_recall(true_stability[i], (start + timedelta(days=days) - last_seen[i]).days)
        for i in range(cards)
    ]
    return Outcome(
        scheduler=scheduler,
        days=days,
        reviews=reviews,
        lapses=lapses,
        final_recall=sum(final) / len(final),
        recall_samples=samples,
    )


def compare(days: int = 365, cards: int = 50, seeds: tuple[int, ...] = (1, 2, 3, 4, 5)) -> dict:
    """Both schedulers over several seeds, so one lucky run cannot decide it."""
    out: dict[str, dict] = {}
    for name in SCHEDULERS:
        runs = [simulate(name, days=days, cards=cards, seed=s) for s in seeds]
        out[name] = {
            "reviews": sum(r.reviews for r in runs) / len(runs),
            "lapses": sum(r.lapses for r in runs) / len(runs),
            "mean_recall_at_review": sum(r.mean_recall for r in runs) / len(runs),
            "final_recall": sum(r.final_recall for r in runs) / len(runs),
        }
    return out


def lapse_recovery(scheduler: str) -> list[int]:
    """Intervals after a single lapse on a well-established card.

    This is the behavioural difference the README reports: SM-2 discards the
    card's whole history on one lapse and starts again at one day, while FSRS
    reduces stability and keeps most of it.
    """
    fn = SCHEDULERS[scheduler]
    today = date(2026, 1, 1)
    state = CardState()
    # Establish the card with several good reviews.
    for _ in range(6):
        state = fn(state, GOOD, today)
        today = state.due
    state = fn(state, AGAIN, today)  # one lapse
    intervals = [state.interval]
    for _ in range(4):
        today = state.due
        state = fn(state, GOOD, today)
        intervals.append(state.interval)
    return intervals
