"""Re-freeze the figures each app's prose states.

    python scripts/freeze_app_figures.py            # rewrite the fixture
    python scripts/freeze_app_figures.py --check     # say what moved, write nothing

Not a test. `tests/test_documented_rates.py` compares every app's prose against
`tests/fixtures/app_figures.json`, so a figure that changes fails there with the old
and new values in the message. Run this when the change was deliberate.

Why counts per figure. The fixture used to be `{"05_debug_ceiling": 11}` - the
number of distinct figures in the prose - on the stated grounds that "every number in
every app's prose is pinned by count, so changing one is a deliberate edit to this
table". It is not: a value can change without the count moving. An independent review
rewrote `93.3% survived` to `99.9% survived` and the whole suite stayed green. Only
apps 02 and 03 have a committed measurement run to check values against, so 56 of the
104 figures had no value-level protection of any kind.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
OUT = ROOT / "tests" / "fixtures" / "app_figures.json"

NOTE = (
    "Every distinct number in each app's prose. This was a table of COUNTS - "
    "`{'05_debug_ceiling': 11}` - so changing a value left the count at 11 and passed: "
    "an independent review rewrote a headline from 93.3% to 99.9% and all 470 tests "
    "stayed green. Only apps 02 and 03 have a committed run to check values against, "
    "which left 56 of these 104 figures with no value-level protection at all. The set "
    "is pinned instead of its size, so a changed value is a figure appearing and a "
    "figure vanishing. That still missed a value swapped for one ALREADY in the set, "
    "which is the common case: each app quotes its run in three regions, so rewriting "
    "one `76.0` to `75.8` in app 04's ABOUT panel moved neither the size nor the "
    "membership. These are counts per figure, so that edit takes `76.0` from twice to "
    "once and `75.8` from once to twice, and either movement fails."
)


def collect() -> dict[str, dict[str, int]]:
    import test_documented_rates as rates  # noqa: PLC0415

    return {
        app.name: {
            figure: count
            for figure, count in sorted(
                rates.figures(app).items(), key=lambda kv: (len(kv[0]), kv[0])
            )
        }
        for app in rates.APPS
    }


def _counts(held) -> dict[str, int]:
    """The held figures as counts, whatever shape the fixture is in.

    The fixture has been a count per app, then a list of distinct figures, now a count
    per figure. A list is read as one statement each so that the first run after the
    change can report what moved instead of raising on the old shape.
    """
    if isinstance(held, dict):
        return dict(held)
    return {str(value): 1 for value in held}


def main(argv: list[str]) -> int:
    found = collect()
    held = json.loads(OUT.read_text(encoding="utf-8"))["apps"] if OUT.is_file() else {}

    moved = False
    for app in sorted(set(found) | set(held)):
        here, there = found.get(app, {}), _counts(held.get(app, {}))
        gained = sorted(f"{k} x{v}" for k, v in here.items() if there.get(k) != v)
        lost = sorted(f"{k} x{v}" for k, v in there.items() if here.get(k) != v)
        if gained or lost:
            moved = True
            print(f"  {app}")
            if lost:
                print(f"    gone:  {', '.join(lost)}")
            if gained:
                print(f"    new:   {', '.join(gained)}")

    if not moved:
        print(
            f"nothing moved; {sum(len(v) for v in found.values())} distinct figures, "
            f"{sum(sum(v.values()) for v in found.values())} statements of them, "
            f"across {len(found)} apps"
        )
        return 0
    if "--check" in argv:
        print("\n--check: nothing written")
        return 1

    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "note": NOTE,
                    "how_to_update": (
                        "python scripts/freeze_app_figures.py, after checking the new "
                        "number is right"
                    ),
                    "apps": found,
                },
                indent=2,
            )
            + "\n"
        )
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
