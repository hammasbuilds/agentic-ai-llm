"""campus-ops against a real schedule.

`products/data/synthea_csv.zip` holds 5,571 real scheduled encounters with a
start, a stop, an organisation, a provider and a patient. That is a timetable:
room, teacher, cohort, span. The mapping is exact, which is why this answers the
question a published timetable dataset would have, on data that is real.

Every figure asserted here was produced by running this code over that file.
"""

import collections

import pytest

from campusops.domain import COHORT, ROOM, TEACHER, publishable
from campusops.schedule import ARCHIVE, bookings, clashes_by_day, report, sessions

pytestmark = pytest.mark.skipif(not ARCHIVE.exists(), reason="Synthea sample not on disk")


@pytest.fixture(scope="module")
def pairs():
    """Distinct overlapping pairs, with the dimensions each trips."""
    out = collections.defaultdict(set)
    for day, found in clashes_by_day().items():
        for clash in found:
            out[(day, clash.first, clash.second)].add(clash.dimension)
    return dict(out)


def test_the_schedule_loads():
    assert len(bookings()) == 5_571
    assert len(sessions()) == len(bookings())


def test_most_days_are_clean():
    r = report()
    assert r.days == 3_440
    assert r.clashing_days == 45
    assert r.clean_days > 0.98


def test_the_three_dimensions_are_nearly_equally_represented():
    counts = report().by_dimension
    assert counts[ROOM] == 37
    assert counts[TEACHER] == 37
    assert counts[COHORT] == 36
    # A checker that looks at one dimension is looking at a third of the problem.


def test_there_are_forty_six_real_overlaps(pairs):
    assert len(pairs) == 46


def test_most_overlaps_trip_every_dimension(pairs):
    both = collections.Counter(frozenset(v) for v in pairs.values())
    assert both[frozenset({ROOM, TEACHER, COHORT})] == 27  # a duplicate booking
    assert both[frozenset({ROOM, TEACHER})] == 10  # one clinician, two patients


def test_a_room_only_checker_misses_the_impossible_ones(pairs):
    # THE FINDING. Nine overlaps trip the cohort dimension ALONE: the same
    # person booked at two different sites with two different staff at the same
    # time. That is physically impossible and completely invisible to a checker
    # looking at rooms.
    cohort_only = [v for v in pairs.values() if v == {COHORT}]
    assert len(cohort_only) == 9

    caught_by_rooms = [v for v in pairs.values() if ROOM in v]
    assert len(caught_by_rooms) == 37
    assert len(caught_by_rooms) / len(pairs) == pytest.approx(0.80, abs=0.02)


def test_a_double_booked_teacher_is_as_common_as_a_double_booked_room(pairs):
    with_teacher = [v for v in pairs.values() if TEACHER in v]
    with_room = [v for v in pairs.values() if ROOM in v]
    assert len(with_teacher) == len(with_room) == 37


def test_a_day_with_a_clash_is_not_publishable():
    day, found = next((d, c) for d, c in clashes_by_day().items() if c)
    rows = [s for s in sessions() if s.day == day]
    assert not publishable(rows)


def test_a_clean_day_is_publishable():
    clashing = {d for d, c in clashes_by_day().items() if c}
    day = next(s.day for s in sessions() if s.day not in clashing)
    assert publishable([s for s in sessions() if s.day == day])


def test_a_missing_schedule_is_reported_rather_than_faked():
    from campusops.schedule import ScheduleMissingError

    with pytest.raises(ScheduleMissingError):
        bookings(str(ARCHIVE.parent / "nope.zip"))


# -- the branch that reads the real schedule ----------------------------------


def test_the_default_day_is_one_that_actually_clashes():
    """`triage` has two branches and only the supplied one was ever run.

    Every test in `test_domain.py` and `test_graph.py` passes `sessions`, so the branch
    that reads the real timetable - and picks a day deliberately, because "a clean day
    exercises nothing" - was never exercised. The overlap predicate it feeds is the
    whole product, and a mutation there survived the entire suite.
    """
    from campusops.agents import triage

    out = triage({})
    assert out["clashes"], "the default day has no clash, so the branch demonstrates nothing"
    assert out["publishable"] is False
    assert set(out["summary_subject"]) <= {"room", "teacher", "cohort"}
    assert set(out["summary_subject"]) == {d for d, _, _ in out["clashes"]}


def test_all_three_clash_types_appear_on_the_default_day():
    """Three dimensions, not one - which is the README's claim about this product."""
    from campusops.agents import triage

    assert {d for d, _, _ in triage({})["clashes"]} == {"room", "teacher", "cohort"}


def test_a_day_with_no_clash_is_publishable():
    """The other direction. A predicate that finds a clash everywhere is not a
    predicate, and `publishable` would be False for every timetable ever."""
    from campusops.agents import _by_day, triage

    clean = sorted(day for day, found in _by_day().items() if not found)
    assert clean, "no day in the real schedule is clean, which is itself suspicious"

    out = triage({"day": clean[0]})
    assert out["clashes"] == []
    assert out["publishable"] is True


def test_the_named_day_is_the_day_read():
    """`s.day == day` is the filter. Inverted, it reads every OTHER day's sessions -
    5,500 of them instead of a handful - and finds clashes that are not clashes."""
    from campusops.agents import _real_sessions, triage

    by_day: dict[str, list] = {}
    for session in _real_sessions():
        by_day.setdefault(session.day, []).append(session)

    day = sorted(day for day, found in _by_day_safe().items() if found)[0]
    out = triage({"day": day})
    ids = {first for _, first, _ in out["clashes"]} | {
        second for _, _, second in out["clashes"]
    }
    assert ids <= {s.id for s in by_day[day]}, (
        "a clash names a session from another day, so the day filter is inverted"
    )


def _by_day_safe():
    from campusops.agents import _by_day

    return _by_day()


def test_back_to_back_sessions_in_one_room_do_not_clash():
    """The half-open rule, on the real timetable rather than a constructed pair.

    `overlaps` reads `self.start < other.end and other.start < self.end`, and its
    docstring says "a session ending at 10:00 does not clash with one starting then".
    Mutating the first `<` to `<=` makes every back-to-back pair a room clash, and the
    whole suite - including the day-level tests above - stayed green: nothing anywhere
    looked at a boundary.

    The real schedule has 99 same-room pairs where one ends exactly when the next
    starts, so this is the ordinary case rather than an edge one.
    """
    from collections import defaultdict

    from campusops.agents import _real_sessions

    by_room = defaultdict(list)
    for session in _real_sessions():
        by_room[(session.day, session.room)].append(session)

    adjacent = []
    for group in by_room.values():
        group.sort(key=lambda s: s.start)
        adjacent += [(a, b) for a, b in zip(group, group[1:], strict=False) if a.end == b.start]

    assert len(adjacent) > 10, f"only {len(adjacent)} back-to-back pairs; too few to claim this"
    for first, second in adjacent[:50]:
        assert not first.overlaps(second), (first.id, second.id, first.end, second.start)
        assert not second.overlaps(first), (second.id, first.id)


def test_a_one_minute_overlap_in_one_room_does_clash():
    """The other side of the boundary, so the rule is pinned from both directions."""
    from campusops.domain import Session

    a = Session("a", "mon", 100, 200, "r", "t", "c")
    b = Session("b", "mon", 199, 300, "r", "t", "c")
    touching = Session("c", "mon", 200, 300, "r", "t", "c")
    assert a.overlaps(b) and b.overlaps(a)
    assert not a.overlaps(touching) and not touching.overlaps(a)
