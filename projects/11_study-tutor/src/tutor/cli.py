"""Command line for study-tutor. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .scheduler import GRADES, SCHEDULERS, Card, CardState, due_cards
from .simulate import compare, lapse_recovery


class DeckError(ValueError):
    """The deck could not be read. The reason is in the message.

    Every one of these came out as a traceback: an unreadable deck gave
    `JSONDecodeError`, a missing one `FileNotFoundError`, a locked one
    `PermissionError`, and an empty file the first of those - four stack traces for the
    four ordinary ways a path argument goes wrong, from the command a reader runs first.
    """


def _load(path: Path) -> list[Card]:
    # Asked before reading, because the two platforms disagree about what reading a
    # directory raises: `IsADirectoryError` on Linux and `PermissionError` on Windows.
    # Caught as an exception, the Windows message read "permission denied" for a path
    # the reader can read perfectly well - a message describing the wrong problem,
    # which is the thing this whole change is about.
    if path.is_dir():
        raise DeckError(f"{path} is a directory, not a deck file")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DeckError(f"no deck at {path}") from None
    except PermissionError:
        raise DeckError(f"{path} cannot be read: permission denied") from None
    except UnicodeDecodeError:
        raise DeckError(f"{path} is not UTF-8 text; a deck is JSON") from None

    if not text.strip():
        raise DeckError(f"{path} is empty ({path.stat().st_size} bytes); a deck is a JSON list")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as bad:
        raise DeckError(f"{path} is not valid JSON: {bad}") from None
    if not isinstance(raw, list):
        raise DeckError(f"{path} holds a {type(raw).__name__}; a deck is a JSON list of cards")

    out = []
    for position, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise DeckError(
                f"{path}: card {position} is a {type(item).__name__}, not an object"
            )
        for required in ("question", "answer"):
            if required not in item:
                raise DeckError(f"{path}: card {position} has no {required!r}")
        state = item.get("state")
        if state is not None and not isinstance(state, dict):
            raise DeckError(f"{path}: card {position} has a non-object 'state'")
        due = (state or {}).get("due")
        if due is not None:
            try:
                date.fromisoformat(due)
            except (TypeError, ValueError):
                raise DeckError(
                    f"{path}: card {position} has due={due!r}; it must be YYYY-MM-DD"
                ) from None
    for item in raw:
        state = item.get("state", {})
        due = state.get("due")
        out.append(
            Card(
                question=item["question"],
                answer=item["answer"],
                state=CardState(
                    stability=state.get("stability", 0.0),
                    difficulty=state.get("difficulty", 5.0),
                    interval=state.get("interval", 0),
                    reps=state.get("reps", 0),
                    lapses=state.get("lapses", 0),
                    ease=state.get("ease", 2.5),
                    due=date.fromisoformat(due) if due else None,
                ),
            )
        )
    return out


def _save(path: Path, cards: list[Card]) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "question": c.question,
                    "answer": c.answer,
                    "state": {
                        "stability": c.state.stability,
                        "difficulty": c.state.difficulty,
                        "interval": c.state.interval,
                        "reps": c.state.reps,
                        "lapses": c.state.lapses,
                        "ease": c.state.ease,
                        "due": c.state.due.isoformat() if c.state.due else None,
                    },
                }
                for c in cards
            ],
            indent=2,
        ),
        encoding="utf-8",
    )


def _review_command(args: argparse.Namespace) -> int:
    path = Path(args.deck)
    cards = _load(path)
    today = date.today()
    pending = due_cards(cards, today)
    if not pending:
        print("Nothing due today.")
        return 0

    print(f"{len(pending)} card(s) due.\n")
    for card in pending:
        print(f"  {card.question}")
        input("  [enter to reveal] ")
        print(f"  {card.answer}")
        while True:
            raw = input("  grade 1=again 2=hard 3=good 4=easy: ").strip()
            if raw.isdigit() and int(raw) in GRADES:
                break
        card.review(int(raw), today, scheduler=args.scheduler)
        print(f"  next in {card.state.interval} day(s)\n")

    _save(path, cards)
    print(f"saved {path}")
    return 0


def _compare_command(args: argparse.Namespace) -> int:
    print("Interval (days) after one lapse on a well-established card:\n")
    for name in SCHEDULERS:
        print(f"  {name:5s} {lapse_recovery(name)}")
    print()
    results = compare(days=args.days, cards=args.cards)
    print(
        f"{'scheduler':10s} {'reviews':>9s} {'lapses':>8s} "
        f"{'recall@review':>14s} {'final recall':>13s}"
    )
    for name, row in results.items():
        print(
            f"{name:10s} {row['reviews']:9.0f} {row['lapses']:8.0f} "
            f"{row['mean_recall_at_review']:13.1%} {row['final_recall']:12.1%}"
        )
    print("\nAveraged over 5 seeds. The learner is a forgetting curve, not a person.")
    return 0


def _due_command(args: argparse.Namespace) -> int:
    cards = _load(Path(args.deck))
    pending = due_cards(cards, date.today())
    print(f"{len(pending)} of {len(cards)} card(s) due")
    for card in pending[:20]:
        due = card.state.due.isoformat() if card.state.due else "new"
        print(f"  {due}  {card.question[:60]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="study-tutor",
        description="Spaced repetition with a deterministic scheduler.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("review", help="review the cards due today")
    r.add_argument("deck")
    r.add_argument("--scheduler", choices=sorted(SCHEDULERS), default="fsrs")
    r.set_defaults(func=_review_command)

    d = sub.add_parser("due", help="list what is due")
    d.add_argument("deck")
    d.set_defaults(func=_due_command)

    c = sub.add_parser("compare", help="SM-2 against FSRS on identical histories")
    c.add_argument("--days", type=int, default=365)
    c.add_argument("--cards", type=int, default=50)
    c.set_defaults(func=_compare_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DeckError as bad:
        # Exit 2 and one line. A traceback tells the reader where this program's
        # `json.loads` is, which is not what they got wrong.
        print(f"{bad}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
