"""The substrate with nothing running behind it.

`apps/_platform` is what the ten apps sit on: a Redis generation cache, a Kafka progress
bus, an Ollama client. The README claims an app boots and serves with none of those
present, and that claim is the difference between a demo someone can open and a demo
that needs three services first.

Nothing here starts a broker, a cache or a model. That is the point: every test below
runs on a machine with none of them, which is the configuration the claim is about and
the one CI has. The cache key is tested as a key - two prompts that differ must not
share a cached answer, which would silently serve one app's generation to another.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._platform import bus, cache, model  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ---- the cache key -------------------------------------------------------------------


def test_the_same_request_gets_the_same_key():
    """Several apps ask the model identical questions; that is what the cache is for."""
    a = cache.gen_key("qwen2.5-coder:14b", "write a function", 0.0, 7)
    b = cache.gen_key("qwen2.5-coder:14b", "write a function", 0.0, 7)
    assert a == b


@pytest.mark.parametrize(
    "first,second",
    [
        # Every component has to be in the key. A collision here serves one app's
        # generation as another's, and the apps compare models and temperatures for a
        # living - so a key that ignored either would quietly make two arms identical.
        (("m1", "p", 0.0, 1), ("m2", "p", 0.0, 1)),
        (("m", "prompt a", 0.0, 1), ("m", "prompt b", 0.0, 1)),
        (("m", "p", 0.0, 1), ("m", "p", 0.8, 1)),
        (("m", "p", 0.0, 1), ("m", "p", 0.0, 2)),
        (("m", "p", 0.0, None), ("m", "p", 0.0, 0)),
    ],
)
def test_different_requests_get_different_keys(first, second):
    assert cache.gen_key(*first) != cache.gen_key(*second)


def test_the_key_is_bounded_and_prefixed():
    """Keys share a namespace with job state, and cache_stats scans by that prefix."""
    key = cache.gen_key("m", "p" * 100_000, 0.0, None)
    assert key.startswith(cache.GEN_PREFIX)
    assert len(key) < 80


# ---- degraded, which is the normal case on a fresh machine ---------------------------


def test_a_cold_cache_reads_as_a_miss_rather_than_an_error():
    """ "A cold cache is slow, not broken" - the comment in the code, tested."""
    assert run(cache.get_generation("m", "p", 0.0, None)) is None


def test_writing_to_a_cache_that_is_not_there_is_not_an_error():
    run(cache.put_generation("m", "p", 0.0, None, "an answer"))


def test_cache_stats_reports_zeroes_rather_than_raising():
    stats = run(cache.cache_stats())
    assert stats == {"generations": 0, "hit_rate": 0.0, "hits": 0, "misses": 0}


def test_reading_a_job_that_was_never_written_is_none():
    assert run(cache.get_job("no-such-job")) is None


def test_recent_jobs_is_empty_rather_than_an_error():
    assert run(cache.recent_jobs("01_localizer")) == []


def test_the_bus_reports_itself_unavailable_instead_of_raising():
    assert run(bus.producer()) is None
    assert run(bus.available()) is False


def test_the_bus_does_not_leak_a_half_started_client():
    """aiokafka builds its sender in the constructor, so a failed start leaves it for
    the garbage collector to complain about - "Unclosed AIOKafkaProducer" on every
    request, in the window someone is watching, plus a socket left to time out."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run(bus.producer())
        run(bus.replay_completed(limit=1))
    unclosed = [str(w.message) for w in caught if "Unclosed" in str(w.message)]
    assert unclosed == []


def test_emitting_progress_with_no_broker_is_not_an_error():
    """An app must finish its work when the bus is down, not fail on the way out."""
    run(bus.emit_progress("job-1", "01_localizer", 1, 10, "a note"))
    run(bus.emit_completed("job-1", "01_localizer", {"done": True}))


def test_replay_returns_nothing_rather_than_raising():
    assert run(bus.replay_completed(limit=5)) == []


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch):
    """Point the client at a closed port.

    Deliberately not "whatever is running": this machine has an Ollama serving a 14B
    model, so a test that called `generate` would occupy the GPU and take minutes, and
    one that asserted `available() is False` would fail here and pass in CI for the
    wrong reason. A closed port is the same code path and costs nothing.
    """
    monkeypatch.setattr(model, "OLLAMA", "http://127.0.0.1:1")
    return model


def test_the_model_reports_itself_unavailable(no_model):
    assert run(no_model.available()) is False


def test_generating_with_no_model_returns_none_rather_than_a_plausible_string(no_model):
    """The one failure mode that must not be graceful in the other direction.

    A substitute answer from a missing model would be scored as the model's output,
    and every number these apps publish would be measuring the fallback.
    """
    assert run(no_model.generate("write a function")) is None


def test_embedding_with_no_model_returns_none(no_model):
    assert run(no_model.embed(["a", "b"])) is None


def test_a_degraded_call_costs_well_under_a_second(monkeypatch: pytest.MonkeyPatch):
    """An absent cache used to cost the full TCP connect timeout - four seconds here.

    A page that read it three times took 12.5 seconds to render, which is the first
    thing anyone opening the demo would see. The cache is an optimisation; waiting four
    seconds to discover it is missing is slower than not having one.
    """
    import time

    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://127.0.0.1:1/0")
    started = time.perf_counter()
    assert run(cache.get_generation("m", "p", 0.0, None)) is None
    assert time.perf_counter() - started < 2.0


def test_the_bus_retries_after_a_cooldown_rather_than_never(monkeypatch):
    """`docker compose up` after starting an app is the normal sequence.

    The unavailable verdict used to be permanent for the life of the process, so an
    app started before the broker stayed degraded until it was restarted.
    """
    monkeypatch.setattr(bus, "_producer", None)
    monkeypatch.setattr(bus, "_available", False)
    monkeypatch.setattr(bus, "_last_attempt", 0.0)
    monkeypatch.setattr(bus, "RETRY_AFTER", 1e9)
    assert run(bus.producer()) is None  # inside the cooldown: no attempt made
    monkeypatch.setattr(bus, "RETRY_AFTER", 0.0)
    assert run(bus.producer()) is None  # past it: tries again, still absent
    assert bus._last_attempt > 0.0
