import pytest

from campusops.domain import (
    COHORT,
    ROOM,
    TEACHER,
    Session,
    clash_rate,
    clashes,
    publishable,
    utilisation,
)


def s(sid, start, end, room="R1", teacher="T1", cohort="C1", day="mon"):
    return Session(sid, day, start, end, room, teacher, cohort)


def test_a_clean_timetable_is_publishable():
    assert publishable([s("a", 540, 600), s("b", 600, 660)])


def test_back_to_back_sessions_do_not_clash():
    # The boundary is half-open: ending at 10:00 and starting at 10:00 is fine.
    assert clashes([s("a", 540, 600), s("b", 600, 660)]) == []


def test_a_double_booked_room_is_a_clash():
    found = clashes(
        [
            s("a", 540, 620, room="R1", teacher="T1", cohort="C1"),
            s("b", 600, 660, room="R1", teacher="T2", cohort="C2"),
        ]
    )
    assert [c.dimension for c in found] == [ROOM]


def test_a_double_booked_teacher_is_a_clash_even_in_different_rooms():
    # The failure the first version shipped.
    found = clashes(
        [
            s("a", 540, 620, room="R1", teacher="T1", cohort="C1"),
            s("b", 600, 660, room="R2", teacher="T1", cohort="C2"),
        ]
    )
    assert [c.dimension for c in found] == [TEACHER]


def test_a_double_booked_cohort_is_a_clash():
    found = clashes(
        [
            s("a", 540, 620, room="R1", teacher="T1", cohort="C1"),
            s("b", 600, 660, room="R2", teacher="T2", cohort="C1"),
        ]
    )
    assert [c.dimension for c in found] == [COHORT]


def test_one_overlap_can_clash_on_several_dimensions_at_once():
    found = clashes([s("a", 540, 620), s("b", 600, 660)])
    assert {c.dimension for c in found} == {ROOM, TEACHER, COHORT}


def test_different_days_never_clash():
    assert clashes([s("a", 540, 660, day="mon"), s("b", 540, 660, day="tue")]) == []


def test_a_timetable_with_a_clash_is_not_publishable():
    assert not publishable([s("a", 540, 620), s("b", 600, 660)])


def test_a_session_ending_before_it_starts_is_refused():
    with pytest.raises(ValueError):
        s("a", 600, 540)


def test_clash_order_is_stable_across_input_order():
    sessions = [s("b", 600, 660), s("a", 540, 620)]
    assert [(c.first, c.second) for c in clashes(sessions)] == [("a", "b")] * 3


def test_utilisation_is_a_count_not_a_judgement():
    assert utilisation([s("a", 540, 600), s("b", 600, 660)], "R1", 480) == pytest.approx(0.25)


def test_a_room_with_no_hours_has_no_utilisation():
    with pytest.raises(ValueError):
        utilisation([], "R1", 0)


def test_clash_rate_reports_the_improvement():
    before = [s("a", 540, 620), s("b", 600, 660)]
    after = [s("a", 540, 600), s("b", 600, 660)]
    assert clash_rate(before, after) == 1.0


def test_a_clean_starting_timetable_has_no_rate_rather_than_dividing_by_zero():
    clean = [s("a", 540, 600)]
    assert clash_rate(clean, clean) == 0.0
