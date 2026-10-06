"""Demonstrate that the recommended `utcnow()` fix is a semantic change.

Python 3.12 deprecates `datetime.utcnow()` and the documentation says to use
`datetime.now(datetime.UTC)` instead. Applied mechanically, that replacement
changes a naive datetime into an aware one, and any comparison or subtraction
against a naive datetime elsewhere in the program then raises TypeError.

This script runs both versions of the same small program and prints what each
does. It is the evidence behind `migration-pilot` refusing to apply the
`utcnow-deprecated` rule automatically.

    python scripts/prove_utcnow.py
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime, timedelta


def session_expired_old(last_seen: datetime) -> bool:
    """The code as written before the deprecation warning appeared."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        now = datetime.utcnow()  # noqa: DTZ003 - the point of the demonstration
    return (now - last_seen) > timedelta(hours=1)


def session_expired_fixed(last_seen: datetime) -> bool:
    """The same function after the documented replacement is applied."""
    now = datetime.now(UTC)
    return (now - last_seen) > timedelta(hours=1)


def main() -> int:
    # A naive timestamp, the kind already sitting in a database column or
    # deserialised from JSON somewhere else in the application.
    #
    # Relative to now, not a fixed date. It was `datetime(2026, 9, 17, 12, 0, 0)`
    # against a one-hour window, so the "before the fix" line printed False on the day
    # it was written and True every day after - a documented output that decayed with
    # the calendar, in a script whose whole job is to be the runnable evidence behind a
    # rule. Ten minutes ago is inside the window for ever.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        stored = datetime.utcnow() - timedelta(minutes=10)  # noqa: DTZ003 - the point
    stored = stored.replace(microsecond=0)

    print("A stored naive timestamp:", stored, f"(tzinfo={stored.tzinfo})")
    print("  ten minutes ago, inside the one-hour session window")
    print()

    print("before the fix:")
    try:
        print(f"  session_expired_old(stored) -> {session_expired_old(stored)}")
    except TypeError as exc:
        print(f"  TypeError: {exc}")

    print()
    print("after applying the documented replacement:")
    try:
        print(f"  session_expired_fixed(stored) -> {session_expired_fixed(stored)}")
    except TypeError as exc:
        print(f"  TypeError: {exc}")
        print()
        print("  The deprecation fix is a one-token edit and it changed the return")
        print("  type from naive to aware. Nothing in the diff says so, the file")
        print("  still imports cleanly, and the failure appears at runtime in a")
        print("  function the diff never touched.")
        return 0

    print()
    print("  No error - this corpus happens to compare only aware datetimes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
