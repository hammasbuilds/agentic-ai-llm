"""fleet-desk against a routing instance with a proven optimal answer.

Six TSPLIB instances with their proven optimal tours — eil51, berlin52, st70,
pr76, kroA100 and ch150, 51 to 150 stops. berlin52 is the one the headline
figures below are quoted on; the other five are what show that the headline is
not a constant.

That pairing is what turns "do not let a model plan a route" from an assertion
into a number. Every figure asserted here was produced by running this code over
those files.
"""

import statistics

import pytest

from fleetdesk.domain import Comparison, cost
from fleetdesk.tsplib import (
    INSTANCE,
    OPTIMAL,
    PUBLISHED,
    by_index,
    cities,
    euc_2d,
    excess,
    instance,
    matrix,
    nearest_neighbour,
    optimal_tour,
    sweep,
    tour_length,
)

pytestmark = pytest.mark.skipif(
    not (INSTANCE.exists() and OPTIMAL.exists()), reason="TSPLIB files not on disk"
)


def test_the_instance_loads():
    assert len(cities()) == 52
    assert len(optimal_tour()) == 52
    assert set(optimal_tour()) == {c.id for c in cities()}


def test_the_computed_optimum_matches_the_published_one():
    # 7542 is berlin52's published optimum. Reaching it from the coordinates
    # is what proves the EUC_2D rounding rule is implemented correctly —
    # using raw floats gives a number close enough to look right and wrong
    # enough to disagree with every published figure.
    assert tour_length(list(optimal_tour())) == 7542


def test_euc_2d_rounds_to_the_nearest_integer():
    a, b = cities()[0], cities()[1]
    assert isinstance(euc_2d(a, b), int)
    assert euc_2d(a, b) == euc_2d(b, a)


def test_visiting_stops_in_listed_order_is_three_times_the_distance():
    # What a model produces when asked to order stops it cannot measure: a plan
    # that visits everything exactly once and is not a route.
    assert tour_length(by_index()) == 22_205
    assert excess(by_index()) == pytest.approx(1.944, abs=0.01)


def test_the_most_plausible_reasoning_a_model_can_do_is_ninety_per_cent_worse():
    # THE FINDING. "Go round the city in a circle" is a genuinely sensible idea,
    # it is the kind of thing a model can actually reason about, and it is
    # 92% worse than optimal on real coordinates.
    assert tour_length(sweep()) == 14_497
    assert excess(sweep()) == pytest.approx(0.922, abs=0.01)


def test_even_a_proper_greedy_heuristic_is_a_fifth_worse():
    assert tour_length(nearest_neighbour()) == 8_980
    assert excess(nearest_neighbour()) == pytest.approx(0.191, abs=0.01)


def test_and_the_greedy_result_depends_on_where_it_starts():
    lengths = [tour_length(nearest_neighbour(start)) for start in range(1, 53)]
    assert min(lengths) == 8_181
    assert max(lengths) == 10_298
    assert statistics.median(lengths) == pytest.approx(9_297, abs=5)
    # A 26% spread from the starting stop alone, with the algorithm unchanged.
    assert max(lengths) / min(lengths) > 1.25


def test_every_published_optimum_is_reproduced_from_the_coordinates():
    # Six independent checks on the EUC_2D rounding rule. One instance agreeing
    # could be luck; six, across 51 to 150 stops and four orders of magnitude of
    # tour length, is the rule being implemented correctly.
    for name, published in PUBLISHED.items():
        inst, opt = instance(name)
        assert tour_length(list(optimal_tour(opt)), inst) == published, name


def test_the_circle_gets_worse_as_the_fleet_grows():
    # THE FINDING, properly. berlin52's 92% is mid-range and not the headline:
    # the sweep's excess RISES with the number of stops, from 54% at 51 to 181%
    # at 150. A single instance cannot show that, and a fleet product whose
    # instance has 52 stops is the least interesting case it will ever see.
    excesses = {}
    for name in PUBLISHED:
        inst, opt = instance(name)
        best = tour_length(list(optimal_tour(opt)), inst)
        excesses[name] = tour_length(sweep(inst), inst) / best - 1

    assert excesses["eil51"] == pytest.approx(0.540, abs=0.01)
    assert excesses["ch150"] == pytest.approx(1.814, abs=0.01)
    assert min(excesses.values()) > 0.5  # never close to acceptable
    # The two largest instances are the two worst.
    worst = sorted(excesses, key=excesses.get)[-2:]
    assert set(worst) == {"kroA100", "ch150"}


def test_nearest_neighbour_degrades_too_but_far_less():
    excesses = {}
    for name in PUBLISHED:
        inst, opt = instance(name)
        best = tour_length(list(optimal_tour(opt)), inst)
        excesses[name] = tour_length(nearest_neighbour(1, inst), inst) / best - 1
    assert min(excesses.values()) == pytest.approx(0.191, abs=0.01)
    assert max(excesses.values()) == pytest.approx(0.419, abs=0.01)
    # A real heuristic stays within half of optimal where the circle doubles it.
    assert max(excesses.values()) < 0.5


def test_visiting_in_listed_order_measures_the_file_not_the_method():
    # A caution about the weakest baseline. "Listed order" ranges from 39% worse
    # to 699% worse across these six, because TSPLIB files are not shuffled —
    # pr76's points happen to be written in a spatially coherent order, so there
    # the naive ordering BEATS the circular sweep. A benchmark built on listed
    # order is measuring how the file was written.
    excesses = {}
    for name in PUBLISHED:
        inst, opt = instance(name)
        best = tour_length(list(optimal_tour(opt)), inst)
        excesses[name] = tour_length(by_index(inst), inst) / best - 1
    assert excesses["pr76"] == pytest.approx(0.394, abs=0.01)
    assert excesses["kroA100"] == pytest.approx(7.993, abs=0.02)
    assert max(excesses.values()) / min(excesses.values()) > 15

    pr76, _ = instance("pr76")
    assert tour_length(by_index(pr76), pr76) < tour_length(sweep(pr76), pr76)


def test_the_product_costs_a_route_on_the_same_matrix():
    # The domain core, fed the real instance rather than a toy one.
    m = matrix()
    order = [str(i) for i in optimal_tour()]
    depot = order[0]
    stops = set(order[1:])
    assert cost(order + [depot], m, stops, depot) == 7542


def test_a_challenger_is_scored_against_the_solver_not_asserted_about():
    solver = tour_length(list(optimal_tour()))
    challenger = tour_length(sweep())
    result = Comparison(solver=solver, challenger=challenger)
    assert not result.challenger_won
    assert result.pct_worse == pytest.approx(0.922, abs=0.01)


def test_a_missing_instance_is_reported_rather_than_faked():
    from fleetdesk.tsplib import InstanceMissingError

    with pytest.raises(InstanceMissingError):
        cities(str(INSTANCE.parent / "nope.tsp"))


# -- the branch that builds the real instance ---------------------------------


def test_the_real_instance_is_a_tour_of_every_stop():
    """`_instance` has two branches and only the supplied one was ever run.

    Its own docstring says so: "Supplied directly by the unit tests. Otherwise the real
    TSPLIB berlin52 instance." Every test in `test_domain.py` and `test_graph.py`
    supplies `matrix`, so a mutation on the other path - the `s != depot` that keeps the
    challenger from visiting the depot twice in the middle - mangles the route, and the
    whole suite stayed green.
    """
    from fleetdesk.agents import _instance

    matrix, stops, depot, solver, challenger = _instance({})

    assert len(stops) == 51, len(stops)
    assert len(matrix) == 52 * 51, len(matrix)

    for name, route in (("solver", solver), ("challenger", challenger)):
        assert route[0] == depot and route[-1] == depot, (name, route[0], route[-1])
        middle = route[1:-1]
        assert sorted(middle) == sorted(stops), (
            f"{name} does not visit every stop exactly once: "
            f"{len(middle)} hops over {len(stops)} stops"
        )
        assert depot not in middle, f"{name} returns to the depot mid-route"


def test_every_hop_in_both_routes_has_a_distance():
    """A route is only costable if the matrix covers it. A missing pair is a KeyError
    inside the cost function, which is where a mangled route shows up."""
    from fleetdesk.agents import _instance

    matrix, _, _, solver, challenger = _instance({})
    for name, route in (("solver", solver), ("challenger", challenger)):
        missing = [
            (a, b) for a, b in zip(route, route[1:], strict=False) if (a, b) not in matrix
        ]
        assert not missing, (name, missing[:3])


def test_the_solver_route_is_not_worse_than_the_challenger():
    """berlin52's optimum is proven, so this direction is not a coin flip - and it is
    the product's entire claim."""
    from fleetdesk.agents import _instance

    matrix, _, _, solver, challenger = _instance({})

    def cost(route):
        return sum(matrix[(a, b)] for a, b in zip(route, route[1:], strict=False))

    assert cost(solver) <= cost(challenger), (cost(solver), cost(challenger))


def test_a_supplied_matrix_is_still_used_rather_than_the_real_one():
    """The other direction: the unit tests' instance must not be silently replaced."""
    from fleetdesk.agents import _instance

    matrix, stops, depot, solver, challenger = _instance(
        {
            "matrix": {"d->a": 1, "a->d": 1},
            "stops": ["a"],
            "depot": "d",
            "solver_route": ["d", "a", "d"],
            "challenger_route": ["d", "a", "d"],
        }
    )
    assert matrix == {("d", "a"): 1, ("a", "d"): 1}
    assert (stops, depot) == ({"a"}, "d")
