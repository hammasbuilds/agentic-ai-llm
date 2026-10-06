import pytest

from agentplatform.admission import Controller, Gpu


def quadro() -> Gpu:
    # Quadro RTX 5000, 16 GB, a 14B at Q4 and 3 GB of KV cache per slot.
    return Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=3000)


def test_slots_come_from_vram_not_from_partition_count():
    assert quadro().max_slots == 2


def test_a_card_that_barely_fits_the_model_still_gets_one_slot():
    assert Gpu(total_mb=10000, model_mb=9000, kv_cache_mb_per_slot=3000).max_slots == 1


def test_a_model_that_does_not_fit_is_refused_up_front():
    with pytest.raises(ValueError):
        Gpu(total_mb=8000, model_mb=9000, kv_cache_mb_per_slot=3000)


def test_admission_stops_at_the_slot_count():
    c = Controller(quadro())
    assert c.admit("acme", 500).admitted
    assert c.admit("acme", 500).admitted
    third = c.admit("acme", 500)
    assert not third.admitted
    assert "slots busy" in third.reason


def test_releasing_frees_a_slot():
    c = Controller(quadro())
    c.admit("acme", 1)
    c.admit("acme", 1)
    c.release()
    assert c.admit("acme", 1).admitted


def test_budget_is_checked_before_the_gpu_is_touched():
    c = Controller(quadro(), daily_token_budget={"acme": 1000})
    assert c.admit("acme", 900).admitted
    refused = c.admit("acme", 200)
    assert not refused.admitted
    assert "daily budget" in refused.reason
    assert c.in_flight == 1  # the refused request never took a slot


def test_a_tenant_with_no_budget_is_unlimited():
    c = Controller(quadro(), daily_token_budget={"acme": 10})
    assert c.admit("other", 10_000).admitted


def test_releasing_more_than_was_admitted_is_a_bug_not_a_shrug():
    with pytest.raises(RuntimeError):
        Controller(quadro()).release()


# -- a reservation that is never settled ----------------------------------


def test_usage_is_what_the_generation_cost_not_what_it_might_have_cost():
    """`used()` was a sum of worst cases reported as consumption.

    `admit` charged `len(prompt.split()) + max_tokens` and nothing ever corrected
    it. A 19-word prompt answered in four tokens stood at 515 - 129 times its cost -
    so a 100,000-token daily budget allowed 194 calls where the real usage allows
    25,000. The tenant hit its limit having used 0.4% of it.
    """
    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    decision = controller.admit("acme", 515)
    assert decision.admitted
    assert controller.reserved("acme") == 515, "held while the generation runs"
    assert controller.settled("acme") == 0, "nothing measured yet"

    controller.release(decision.reservation, 4)
    assert controller.settled("acme") == 4
    assert controller.reserved("acme") == 0
    assert controller.estimated("acme") == 0
    assert controller.used("acme") == 4


def test_a_reservation_is_counted_against_the_budget_while_it_is_held():
    """Reserving is the point: two concurrent calls must not both fit a budget one
    of them would exhaust."""
    controller = Controller(
        Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200),
        {"acme": 600},
    )
    first = controller.admit("acme", 515)
    assert first.admitted
    assert not controller.admit("acme", 515).admitted, "the first is still in flight"

    controller.release(first.reservation, 4)
    assert controller.admit("acme", 515).admitted, "settled at 4, so there is room"


def test_a_generation_that_raised_keeps_its_estimate_but_is_not_called_measured():
    """The safe assumption about an unmeasured call is not that it was free."""
    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    decision = controller.admit("acme", 515)
    controller.release(decision.reservation, None)

    assert controller.estimated("acme") == 515
    assert controller.settled("acme") == 0, "nothing was measured, so nothing is settled"
    assert controller.used("acme") == 515
    assert controller.in_flight == 0, "and the slot is free either way"


def test_a_cache_hit_costs_the_tenant_nothing():
    """It reaches no model. It used to be charged the full estimate twice over."""
    from agentplatform.llm import Budgeted, Cached, Recorded
    from agentplatform.ports import InMemoryCache

    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    model = Budgeted(
        Cached(Recorded(tag="q", script={"a deal": "yes"}), InMemoryCache()),
        controller,
        "acme",
    )

    first = model.generate("a deal")
    after_one = controller.used("acme")
    assert after_one == first.total_tokens

    second = model.generate("a deal")
    assert second.cached is True
    assert second.total_tokens == 0
    assert controller.used("acme") == after_one, "a second call that cost nothing"


def test_the_slot_is_freed_when_the_model_raises():
    from agentplatform.llm import Budgeted

    class Down:
        tag = "q"

        def generate(self, prompt, *, max_tokens=512):
            raise RuntimeError("down")

    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    model = Budgeted(Down(), controller, "acme")
    with pytest.raises(RuntimeError, match="down"):
        model.generate("x y z")
    assert controller.in_flight == 0
    assert controller.estimated("acme") == 515
    assert controller.settled("acme") == 0


def test_releasing_a_reservation_that_is_not_open_is_a_bug():
    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    decision = controller.admit("acme", 10)
    controller.release(decision.reservation, 10)
    with pytest.raises(RuntimeError, match="more generations than were admitted"):
        controller.release(decision.reservation, 10)

    other = controller.admit("acme", 10)
    with pytest.raises(RuntimeError, match="is not open"):
        controller.release(other.reservation + 99, 10)


def test_usage_separates_what_was_measured_from_what_was_assumed():
    """Three numbers, because they are three different claims."""
    controller = Controller(Gpu(total_mb=16384, model_mb=9000, kv_cache_mb_per_slot=1200))
    done = controller.admit("acme", 500)
    controller.release(done.reservation, 7)
    failed = controller.admit("acme", 500)
    controller.release(failed.reservation, None)
    running = controller.admit("acme", 500)

    assert controller.settled("acme") == 7
    assert controller.estimated("acme") == 500
    assert controller.reserved("acme") == 500
    assert controller.used("acme") == 1007
    controller.release(running.reservation, 9)
    assert (controller.settled("acme"), controller.used("acme")) == (16, 516)
