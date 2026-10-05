"""Command line for study-tutor. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .scheduler import GRADES, SCHEDULERS, Card, CardState, due_cards
from .simulate import compare, lapse_recovery


def _load(path: Path) -> list[Card]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
