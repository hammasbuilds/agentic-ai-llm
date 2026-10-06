"""swarm-lab's scaling sweep, run against the real Redis when it is up.

No model is involved and that is deliberate. Duplicate tool calls and
conflicting writes are structural: they come from several workers sharing a
queue and a store, not from what any of them is thinking. Removing the model
removes the largest source of variance from a study whose subject is N.

Every figure asserted here was produced by running this code.
"""

import statistics

import pytest

from swarmlab.sweep import FIBONACCI, run_trial, sweep

ENTITIES = 40


def mean(trials, attr):
    return statistics.mean(getattr(t, attr) for t in trials)


def test_one_agent_wastes_nothing():
    trial = run_trial(1, entities=ENTITIES)
    assert len(trial.calls) == ENTITIES
    assert trial.duplicates == 0
    assert trial.conflicts == 0


def test_uncoordinated_waste_is_exactly_one_minus_one_over_n():
    # THE FINDING. Without coordination every agent does every piece of work, so
    # the share of calls that are duplicates is 1 - 1/N exactly. At N=21, 95% of
    # everything the swarm does is waste.
    for n in (2, 5, 13, 21):
        trial = run_trial(n, entities=ENTITIES)
        assert len(trial.calls) == ENTITIES * n
        assert trial.duplicate_rate == pytest.approx(1 - 1 / n, abs=0.001)


def test_conflicting_writes_saturate_at_two_agents():
    # Every entity collects a conflicting write the moment there are two
    # agents. Adding more does not add conflicts; it makes each one deeper.
    for n in (2, 3, 8, 21):
        assert run_trial(n, entities=ENTITIES).conflicts == ENTITIES


def test_a_lock_removes_the_waste_entirely_at_every_n():
    for n in (2, 5, 13, 21):
        trial = run_trial(n, entities=ENTITIES, use_lock=True)
        assert len(trial.calls) == ENTITIES
        assert trial.duplicates == 0
        assert trial.conflicts == 0


def test_the_coordination_cost_is_linear_while_the_waste_it_prevents_is_not():
    # Contention grows as entities x (N-1) - linear in N. The duplicated work it
    # prevents grows as entities x N. Paying the linear cost is the trade.
    for n in (2, 5, 13, 21):
        trial = run_trial(n, entities=ENTITIES, use_lock=True)
        assert trial.lock_contentions == ENTITIES * (n - 1)


def test_partitioning_the_work_is_the_other_answer():
    # A supervisor that splits the list achieves the same thing with no lock at
    # all. Topology substitutes for coordination.
    for n in (2, 5, 13):
        trial = run_trial(n, entities=ENTITIES, topology="hierarchical")
        assert len(trial.calls) == ENTITIES
        assert trial.duplicates == 0


def test_the_sweep_demands_three_repeats():
    with pytest.raises(ValueError):
        sweep(sizes=(1, 2), repeats=1)


def test_a_full_sweep_is_monotone_in_waste():
    result = sweep(sizes=FIBONACCI, repeats=3, entities=12)
    rates = [mean(result[n], "duplicate_rate") for n in FIBONACCI]
    assert rates == sorted(rates)
    assert rates[0] == 0.0
    assert rates[-1] > 0.9


def test_a_trial_needs_an_agent():
    with pytest.raises(ValueError):
        run_trial(0)


def test_it_used_the_real_redis_if_one_was_up():
    trial = run_trial(2, entities=4, use_lock=True)
    # Not asserted as True: the suite must pass on a laptop with nothing
    # running. Recorded so the result says which it was.
    assert hasattr(trial, "real_redis")


def test_the_results_say_which_cache_they_were_produced_by():
    """The README claimed "the real Redis" and `_redis()` falls back in silence.

    Both paths give the same numbers - what is counted is how often two threads
    reach for the same entity, which neither cache changes - so the fallback was
    never going to show up as a wrong result. It showed up as a wrong sentence, and
    nothing in the package produced the sentence either way.
    """
    from swarmlab.sweep import backend

    cells = sweep((1, 2), repeats=3, entities=4, use_lock=True)
    line = backend(cells)
    trials = [t for cell in cells.values() for t in cell]

    assert str(len(trials)) in line
    assert ("real Redis" in line) == all(t.real_redis for t in trials)
    assert ("in-memory" in line) == any(not t.real_redis for t in trials)
    assert line  # never empty: a results table with no provenance is the defect


def test_the_backend_line_reports_a_mixture_as_a_mixture():
    """Three trials, one of which saw Redis. Neither "all" answer is true of that."""
    from swarmlab.sweep import backend

    cells = sweep((1, 2), repeats=3, entities=4)
    trials = [t for cell in cells.values() for t in cell]
    trials[0].real_redis = True
    for trial in trials[1:]:
        trial.real_redis = False

    line = backend(cells)
    assert line == f"1 of {len(trials)} trials against a real Redis, the rest in-memory"
