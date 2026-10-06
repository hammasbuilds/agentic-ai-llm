"""The substrate with Redis actually answering.

`tests/test_platform_degraded.py` is the other half of this file and was, until now, the
only half. Every test in the suite ran on a machine with no Redis, so for the nineteen
async functions in `apps/_platform/cache.py` what was covered was the `except` branch:
"it degrades" was asserted everywhere and "it works" nowhere. An independent review put
it plainly - a cache that returned `None` for every lookup would have passed the whole
suite, and so would one that wrote to the wrong key.

`fakeredis` is a real Redis protocol implementation in-process, so these run in CI with
no container. Where its behaviour differs from a server the difference is named in the
test rather than worked around.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import fakeredis.aioredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._platform import cache  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def redis(monkeypatch):
    """A working Redis for the duration of one test.

    `cache.client()` memoises into a module global, and `call()` keeps a `_down_until`
    stamp from any earlier failure, so both are reset. Without the second one a test
    that ran after a connection failure would take the `Unavailable` short-circuit and
    pass by never reaching Redis at all - the exact shape of the gap this file closes.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "_client", fake)
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(cache, "_LOCAL_JOBS", {})
    yield fake
    run(fake.aclose())


# -- the generation cache, which is the reason Redis is here -------------------


def test_a_generation_written_is_the_generation_read_back(redis):
    run(cache.put_generation("m", "prompt", 0.0, 1, "the answer", 512))
    assert run(cache.get_generation("m", "prompt", 0.0, 1, 512)) == "the answer"


@pytest.mark.parametrize(
    "other",
    [
        ("m2", "prompt", 0.0, 1, 512),
        ("m", "prompt2", 0.0, 1, 512),
        ("m", "prompt", 0.7, 1, 512),
        ("m", "prompt", 0.0, 2, 512),
        ("m", "prompt", 0.0, 1, 128),
    ],
    ids=["model", "prompt", "temperature", "seed", "num_predict"],
)
def test_every_part_of_the_key_separates_two_generations(redis, other):
    """Not just that the keys differ - that the stored value does not leak across.

    `test_platform_degraded.py` asserts the keys are unequal, which it can do with no
    Redis. With one, the stronger claim is checkable: a lookup differing in any one of
    the five parts must miss, or one app serves another app's answer.

    `num_predict` was not one of them, and was not in the key either. It caps the
    generation, so the leak it allowed was a reply truncated where the caller allowed
    more, or longer than the caller asked for - and `localize_eval` asks at 256 and
    128 through this same cache.
    """
    run(cache.put_generation("m", "prompt", 0.0, 1, "the answer", 512))
    assert run(cache.get_generation(*other)) is None


def test_a_miss_is_a_miss_and_not_an_error(redis):
    assert run(cache.get_generation("m", "never written", 0.0, None, 512)) is None


# -- the hit rate, over this cache's own lookups -------------------------------


def test_the_hit_rate_counts_this_caches_lookups_and_nothing_else(redis):
    """It was `keyspace_hits / (keyspace_hits + keyspace_misses)` from `INFO stats`.

    Those are server-wide counters over every key and every database on the instance,
    so job-state reads, the `scan_iter` in this same module and any other process
    sharing the Redis all moved the number reported as the *generation cache's* hit
    rate. Here: three generation lookups, one hit, plus unrelated traffic that must not
    appear in the figure.
    """
    run(cache.put_generation("m", "a", 0.0, None, "A", 512))

    assert run(cache.get_generation("m", "a", 0.0, None, 512)) == "A"  # hit
    assert run(cache.get_generation("m", "b", 0.0, None, 512)) is None  # miss
    assert run(cache.get_generation("m", "c", 0.0, None, 512)) is None  # miss

    # Traffic that is not a generation lookup. Under the old implementation each of
    # these moved the keyspace counters and therefore the reported hit rate.
    run(cache.create_job("j1", "demo", {"limit": 2}))
    run(cache.get_job("j1"))
    run(cache.get_job("absent"))

    stats = run(cache.cache_stats())
    assert (stats["hits"], stats["misses"], stats["lookups"]) == (1, 2, 3)
    assert stats["hit_rate"] == pytest.approx(1 / 3)
    assert stats["generations"] == 1


def test_a_cache_nobody_asked_anything_of_has_no_hit_rate(redis):
    """`None`, not `0.0`.

    Zero is the rate of a cache that missed every time, which is a different and much
    worse report than one that was never consulted. The old code returned `0.0` for
    both, including on the Redis-down path.
    """
    assert run(cache.cache_stats())["hit_rate"] is None
    assert run(cache.cache_stats())["lookups"] == 0


# -- job state -----------------------------------------------------------------


def test_a_job_round_trips_through_redis_with_its_types_intact(redis):
    """`params` goes in as JSON and must come back a dict, not its repr."""
    run(cache.create_job("j1", "demo", {"limit": 7, "model": "m"}))
    run(cache.update_job("j1", status="done", progress=7, result={"score": 0.5}))

    job = run(cache.get_job("j1"))
    assert job["app"] == "demo"
    assert job["status"] == "done"
    assert job["params"] == {"limit": 7, "model": "m"}
    assert job["result"] == {"score": 0.5}
    assert job["total"] == "7"


def test_an_absent_job_is_none_rather_than_an_empty_dict(redis):
    """The page distinguishes them: one is "No such job", the other is a blank run."""
    assert run(cache.get_job("never-created")) is None


def test_recent_jobs_returns_only_this_apps_runs_newest_first(redis):
    for n, app in enumerate(["a", "b", "a"]):
        run(cache.create_job(f"j{n}", app, {"limit": n}))
        run(cache.update_job(f"j{n}", created=str(1000 + n)))

    rows = run(cache.recent_jobs("a"))
    assert [r["job_id"] for r in rows] == ["j2", "j0"]
    assert all(r["app"] == "a" for r in rows)


def test_recent_jobs_honours_its_limit(redis):
    for n in range(5):
        run(cache.create_job(f"j{n}", "a", {}))
        run(cache.update_job(f"j{n}", created=str(1000 + n)))
    assert len(run(cache.recent_jobs("a", limit=2))) == 2


def test_a_job_in_redis_and_one_only_local_both_appear_once(redis):
    """Redis coming back mid-run leaves a job in each place, and neither may be lost.

    `recent_jobs` merges the two and de-duplicates by id; a job created in Redis and
    then updated locally must appear once, with the later fields.
    """
    run(cache.create_job("shared", "a", {}))
    run(cache.update_job("shared", created="1000"))
    cache._LOCAL_JOBS["shared"] = {"app": "a", "status": "done", "created": "1000"}
    cache._LOCAL_JOBS["local-only"] = {"app": "a", "status": "queued", "created": "1001"}

    rows = run(cache.recent_jobs("a"))
    assert [r["job_id"] for r in rows] == ["local-only", "shared"]
    assert next(r for r in rows if r["job_id"] == "shared")["status"] == "done"


def test_local_fields_win_over_redis_for_the_same_job(redis):
    """Redis can go down mid-run, so the local write is the later one."""
    run(cache.create_job("j1", "a", {}))
    cache._LOCAL_JOBS["j1"] = {"status": "done", "result": '{"score": 1}'}

    job = run(cache.get_job("j1"))
    assert job["status"] == "done"
    assert job["result"] == {"score": 1}
    assert job["app"] == "a"  # and the Redis-only fields are still there


# -- ping ----------------------------------------------------------------------


def test_ping_is_true_when_redis_answers(redis):
    assert run(cache.ping()) is True


def test_the_short_circuit_does_not_outlive_the_outage(redis, monkeypatch):
    """`call()` refuses for `DOWN_FOR` seconds after a failure, then tries again.

    Only the refusal was covered. If the stamp were never cleared, a cache that had
    once been missing would stay missing for the life of the process and every test
    asserting degradation would still pass.
    """
    import time

    monkeypatch.setattr(cache, "_down_until", time.monotonic() + 60)
    with pytest.raises(cache.Unavailable):
        run(cache.call(redis.ping))

    monkeypatch.setattr(cache, "_down_until", 0.0)
    assert run(cache.call(redis.ping)) is True
    # A successful call clears the stamp rather than leaving it at its old value.
    assert cache._down_until == 0.0


# -- progress ------------------------------------------------------------------


def test_a_published_tick_reaches_a_subscriber(redis):
    """The pub/sub path, which carries "43 of 250 done" to every open browser."""

    async def body():
        received: list[dict] = []
        ticks = cache.subscribe_progress("j1")
        reader = asyncio.create_task(_take_one(ticks, received))
        # The subscriber arrives after the submit in the real flow too, so the publish
        # is retried until one lands rather than slept on for a fixed interval.
        for _ in range(200):
            if reader.done():
                break
            await cache.publish_progress("j1", {"done": 43, "total": 250})
            await asyncio.sleep(0.01)
        try:
            await asyncio.wait_for(reader, timeout=5)
        finally:
            await ticks.aclose()
        return received

    assert run(body())[0] == {"done": 43, "total": 250}


async def _take_one(ticks, into: list) -> None:
    async for payload in ticks:
        into.append(payload)
        return
