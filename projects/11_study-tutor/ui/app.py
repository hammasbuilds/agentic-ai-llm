"""Reflex UI for study-tutor.

    uv run --extra ui reflex run

Reflex because the whole app is Python and the scheduler is the interesting
part; a separate JS front end would add a build step to show two numbers and a
button. The one design rule here: the interval is always displayed, because a
learner who cannot see when the card returns cannot tell whether the scheduler
is sane.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import reflex as rx  # noqa: E402

from tutor.scheduler import AGAIN, EASY, GOOD, HARD, Card, due_cards  # noqa: E402
from tutor.simulate import lapse_recovery  # noqa: E402

DECK = [
    Card("What does FSRS optimise for?", "A target recall probability at review time."),
    Card(
        "Why must an LLM not pick the interval?",
        "It has no memory model and is not reproducible.",
    ),
    Card(
        "What does SM-2 do on a lapse?",
        "Resets the interval to one day, discarding the history.",
    ),
]


class State(rx.State):
    index: int = 0
    revealed: bool = False
    scheduler: str = "fsrs"
    last_interval: int = 0
    reviewed: int = 0

    @rx.var
    def question(self) -> str:
        pending = due_cards(DECK, date.today())
        if not pending:
            return ""
        return pending[self.index % len(pending)].question

    @rx.var
    def answer(self) -> str:
        pending = due_cards(DECK, date.today())
        if not pending:
            return ""
        return pending[self.index % len(pending)].answer

    @rx.var
    def finished(self) -> bool:
        return not due_cards(DECK, date.today())

    def reveal(self) -> None:
        self.revealed = True

    def grade(self, value: int) -> None:
        pending = due_cards(DECK, date.today())
        if not pending:
            return
        card = pending[self.index % len(pending)]
        card.review(value, date.today(), scheduler=self.scheduler)
        self.last_interval = card.state.interval
        self.reviewed += 1
        self.revealed = False


def grade_button(label: str, value: int, colour: str) -> rx.Component:
    return rx.button(label, on_click=lambda: State.grade(value), color_scheme=colour, size="3")


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("study-tutor", size="6"),
            rx.text(
                "The scheduler is arithmetic over a memory model. The model writes "
                "questions and never chooses an interval.",
                color_scheme="gray",
                size="2",
            ),
            rx.cond(
                State.finished,
                rx.callout("Nothing due. Come back tomorrow.", icon="check"),
                rx.card(
                    rx.vstack(
                        rx.text(State.question, size="5", weight="medium"),
                        rx.cond(
                            State.revealed,
                            rx.vstack(
                                rx.divider(),
                                rx.text(State.answer, color_scheme="gray"),
                                rx.hstack(
                                    grade_button("Again", AGAIN, "red"),
                                    grade_button("Hard", HARD, "orange"),
                                    grade_button("Good", GOOD, "green"),
                                    grade_button("Easy", EASY, "blue"),
                                    spacing="2",
                                ),
                                spacing="3",
                                align="start",
                                width="100%",
                            ),
                            rx.button("Reveal", on_click=State.reveal, size="3"),
                        ),
                        spacing="4",
                        align="start",
                        width="100%",
                    ),
                    width="100%",
                ),
            ),
            rx.cond(
                State.last_interval > 0,
                rx.text(
                    f"Scheduled {State.last_interval} day(s) out.",
                    size="2",
                    color_scheme="gray",
                ),
            ),
            rx.divider(),
            rx.heading("Why the scheduler is not a prompt", size="3"),
            rx.text(
                f"Interval after one lapse on an established card — "
                f"SM-2: {lapse_recovery('sm2')[0]} day, "
                f"FSRS: {lapse_recovery('fsrs')[0]} days. "
                "SM-2 discards the card's entire history; FSRS reduces its stability.",
                size="2",
                color_scheme="gray",
            ),
            spacing="4",
            width="100%",
        ),
        size="2",
    )


app = rx.App()
app.add_page(index, title="study-tutor")
