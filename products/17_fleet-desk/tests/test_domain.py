import pytest

from fleetdesk.domain import (
    Comparison,
    InvalidRouteError,
    MissingLegError,
    compare,
    cost,
    eta_minutes,
    validate,
)

DEPOT = "d"
STOPS = {"a", "b", "c"}


def matrix():
    points = ["d", "a", "b", "c"]
    distances = {
        ("d", "a"): 1000,
        ("a", "d"): 1000,
        ("d", "b"): 2000,
        ("b", "d"): 2000,
        ("d", "c"): 3000,
        ("c", "d"): 3000,
        ("a", "b"): 1200,
        ("b", "a"): 1200,
        ("a", "c"): 2500,
        ("c", "a"): 2500,
        ("b", "c"): 1100,
        ("c", "b"): 1100,
    }
    assert len(points) == 4
    return distances


def test_a_valid_route_costs_the_sum_of_its_legs():
    assert cost(["d", "a", "b", "c", "d"], matrix(), STOPS, DEPOT) == 1000 + 1200 + 1100 + 3000


def test_a_route_that_does_not_return_is_refused():
    with pytest.raises(InvalidRouteError):
        validate(["d", "a", "b", "c"], STOPS, DEPOT)


def test_a_route_that_skips_a_stop_is_refused_rather_than_winning():
    with pytest.raises(InvalidRouteError):
        cost(["d", "a", "b", "d"], matrix(), STOPS, DEPOT)


def test_a_route_that_repeats_a_stop_is_refused():
    with pytest.raises(InvalidRouteError):
        validate(["d", "a", "a", "b", "c", "d"], STOPS, DEPOT)


def test_a_route_visiting_an_unknown_stop_is_refused():
    with pytest.raises(InvalidRouteError):
        validate(["d", "a", "b", "c", "z", "d"], STOPS, DEPOT)


def test_a_missing_distance_raises_instead_of_counting_as_zero():
    sparse = {("d", "a"): 1000}
    with pytest.raises(MissingLegError):
        cost(["d", "a", "b", "c", "d"], sparse, STOPS, DEPOT)


def test_two_routes_are_scored_on_one_matrix():
    result = compare(
        ["d", "a", "b", "c", "d"],
        ["d", "c", "a", "b", "d"],
        matrix(),
        STOPS,
        DEPOT,
    )
    assert result.solver == 6300
    assert result.challenger == 3000 + 2500 + 1200 + 2000
    assert result.delta == result.challenger - result.solver


def test_a_challenger_that_wins_is_reported_as_winning():
    result = Comparison(solver=100, challenger=90)
    assert result.challenger_won
    assert result.pct_worse == pytest.approx(-0.1)


def test_percentage_worse_is_the_headline():
    assert Comparison(solver=1000, challenger=1300).pct_worse == pytest.approx(0.3)


def test_a_zero_cost_solver_route_cannot_be_a_baseline():
    with pytest.raises(ValueError):
        _ = Comparison(solver=0, challenger=10).pct_worse


def test_an_eta_is_arithmetic():
    assert eta_minutes(6000, speed_kmh=30, service_minutes=5) == 17


def test_a_non_positive_speed_is_refused():
    with pytest.raises(ValueError):
        eta_minutes(1000, speed_kmh=0)
