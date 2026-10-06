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
    monkeypatch.setattr(cache, "_down_until", 0.0)  # not already short-circuited
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


# ---- the submit path, which is the one a visitor actually clicks ---------------------
#
# Everything above tests the platform's functions. None of it opened an endpoint, and
# that is exactly where the hole was: with Redis absent, `create_job` was a suppressed
# no-op, so `/run` redirected to a job page that answered 404 while the measurement ran
# to completion in the background and wrote its result through the same suppressed call.
# The answer was computed and thrown away, nothing was logged, and `/`, `/about`,
# `/history` and `/healthz` all kept returning 200 - which is what made it look fine.
#
# The README says "if Redis is down the apps still run". These tests are that sentence.


@pytest.fixture
def degraded_platform(monkeypatch: pytest.MonkeyPatch):
    """Redis, Kafka and the model all at a closed port, and the fallback stores empty."""
    from apps._platform import model

    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(cache, "_LOCAL_JOBS", {})
    monkeypatch.setattr(cache, "_LOCAL_WAITERS", {})
    monkeypatch.setattr(bus, "_producer", None)
    monkeypatch.setattr(bus, "_available", False)
    monkeypatch.setattr(bus, "BOOTSTRAP", "127.0.0.1:1", raising=False)
    monkeypatch.setattr(model, "OLLAMA", "http://127.0.0.1:1")


@pytest.fixture
def degraded(monkeypatch: pytest.MonkeyPatch):
    """One app, with Redis, Kafka and the model all pointed at a closed port.

    The port matters. Pointing the model at "whatever is running" is how a test of the
    degraded path ends up generating on this machine's 14B - which is both slow and the
    opposite of what is being tested.
    """
    import importlib.util

    from apps._platform import model

    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(cache, "_LOCAL_JOBS", {})
    monkeypatch.setattr(cache, "_LOCAL_WAITERS", {})
    monkeypatch.setattr(bus, "_producer", None)
    monkeypatch.setattr(bus, "_available", False)
    monkeypatch.setattr(bus, "BOOTSTRAP", "127.0.0.1:1", raising=False)
    monkeypatch.setattr(model, "OLLAMA", "http://127.0.0.1:1")

    spec = importlib.util.spec_from_file_location(
        "degraded_app", ROOT / "apps" / "05_debug_ceiling" / "app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def test_a_job_submitted_with_no_redis_is_not_thrown_away(degraded):
    """Submit, follow the redirect, read the outcome back. The whole click.

    This is the test that would have failed before the fallback existed: the redirect
    went to a 404 and the outcome existed nowhere, having been written to a cache that
    was not there.

    It used to assert `status == "done"` with a truthy `result`, and it passed - the
    model was at a closed port too, and app 05 returned
    `{"per_round": [0,0,0,0,0], "final_pass": 0.0}`. An independent review pointed out
    that this file's own docstring calls that the worst possible outcome, and that the
    test was certifying it. A run with no model must FAIL and say so; what this test is
    about is that the failure is recorded and readable, which is the Redis half.
    """
    from fastapi.testclient import TestClient

    with TestClient(degraded) as client:
        posted = client.post("/run", data={"limit": 1}, follow_redirects=False)
        assert posted.status_code == 303
        job_id = posted.headers["location"].rsplit("/", 1)[-1]

        assert client.get(f"/job/{job_id}").status_code == 200
        assert client.get(f"/job/{job_id}/result").status_code == 200

        job = run(cache.get_job(job_id))
        assert job is not None, "the job page would answer 404"
        assert job["transport"] == "inline"  # no Kafka, so no worker took it
        assert job["status"] == "error", job
        assert "never reached the model" in job["error"], job["error"]
        assert not job.get("result"), "a failed run must publish no number"


def test_the_progress_stream_ends_instead_of_hanging(degraded):
    """Progress is Redis pub/sub, so with no Redis the stream used to raise inside the
    generator and the page sat on "stream closed" for ever - on a job that had already
    finished. A stream that never ends is how a working run looks like a hung one."""
    from fastapi.testclient import TestClient

    with TestClient(degraded) as client:
        posted = client.post("/run", data={"limit": 1}, follow_redirects=False)
        job_id = posted.headers["location"].rsplit("/", 1)[-1]
        stream = client.get(f"/job/{job_id}/stream")
        assert stream.status_code == 200
        assert "event: done" in stream.text


def test_history_lists_a_job_that_only_exists_locally(degraded):
    from fastapi.testclient import TestClient

    with TestClient(degraded) as client:
        job_id = (
            client.post("/run", data={"limit": 1}, follow_redirects=False)
            .headers["location"]
            .rsplit("/", 1)[-1]
        )
        assert job_id in client.get("/history").text


# ---- the fallback store on its own ---------------------------------------------------


@pytest.fixture
def local_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(cache, "_LOCAL_JOBS", {})
    monkeypatch.setattr(cache, "_LOCAL_WAITERS", {})
    return cache


def test_a_job_written_with_no_redis_can_be_read_back(local_only):
    run(local_only.create_job("j1", "05_debug_ceiling", {"limit": 3}))
    run(local_only.update_job("j1", status="done", result={"solved": 2}))
    job = run(local_only.get_job("j1"))
    assert job["app"] == "05_debug_ceiling"
    assert job["status"] == "done"
    assert job["result"] == {"solved": 2}  # decoded, as the Redis path decodes it
    assert job["params"] == {"limit": 3}


def test_an_unknown_job_is_still_none(local_only):
    """The fallback must not turn every id into a job; 404 is right for a wrong id."""
    assert run(local_only.get_job("never-created")) is None


def test_the_fallback_does_not_grow_without_limit(local_only):
    """A server that runs for a month must not hold every job it ever ran."""
    for n in range(local_only._LOCAL_MAX + 40):
        run(local_only.create_job(f"j{n}", "app", {}))
    assert len(local_only._LOCAL_JOBS) == local_only._LOCAL_MAX
    assert run(local_only.get_job("j0")) is None  # oldest evicted
    assert run(local_only.get_job(f"j{local_only._LOCAL_MAX + 39}")) is not None


def test_recent_jobs_only_returns_the_app_asked_for(local_only):
    run(local_only.create_job("a", "01_localizer", {}))
    run(local_only.create_job("b", "05_debug_ceiling", {}))
    assert [j["job_id"] for j in run(local_only.recent_jobs("05_debug_ceiling"))] == ["b"]


def test_progress_published_with_no_redis_reaches_a_listener(local_only):
    """The queue path, which the end-to-end test above skips: there, the job finishes
    before the browser connects, so the stream answers from the job's status."""

    async def scenario():
        run_id = "j-live"
        await local_only.create_job(run_id, "app", {})
        ticks = []

        async def listen():
            async for payload in local_only.subscribe_progress(run_id):
                ticks.append(payload)
                if payload.get("status") in ("done", "error"):
                    return

        listener = asyncio.ensure_future(listen())
        while not local_only._LOCAL_WAITERS.get(run_id):
            await asyncio.sleep(0.01)  # until the subscription is registered
        await local_only.publish_progress(run_id, {"done": 1, "total": 2, "status": "running"})
        await local_only.publish_progress(run_id, {"status": "done"})
        await asyncio.wait_for(listener, timeout=5)
        return ticks

    ticks = run(scenario())
    assert ticks == [{"done": 1, "total": 2, "status": "running"}, {"status": "done"}]
    assert cache._LOCAL_WAITERS == {}, "the listener left its queue behind"


def test_a_listener_arriving_after_the_job_finished_is_not_left_waiting(local_only):
    """The race the fallback has to survive: an inline run with limit=1 can be over
    before the browser has loaded the page that opens the stream."""

    async def scenario():
        await local_only.create_job("j-late", "app", {})
        await local_only.update_job("j-late", status="done")
        out = []
        async for payload in local_only.subscribe_progress("j-late"):
            out.append(payload)
            break
        return out

    assert run(asyncio.wait_for(scenario(), timeout=5)) == [{"status": "done", "note": ""}]


def test_an_absent_redis_is_discovered_once_rather_than_per_call(local_only):
    """The connect timeout is 0.5s. Three hundred of them is two and a half minutes.

    Shortening the timeout fixed what one call costs; this is about how many calls pay
    it. A job page reads state, reads history and publishes a tick, and every one of
    those used to wait for the same absent server all over again.
    """
    import time as clock

    started = clock.perf_counter()
    for n in range(300):
        run(local_only.create_job(f"many{n}", "app", {}))
    elapsed = clock.perf_counter() - started
    assert elapsed < 5.0, f"300 writes to an absent Redis took {elapsed:.1f}s"


def test_the_breaker_lets_go_once_redis_answers(local_only, monkeypatch):
    """A cooldown that never expired would mean an app started before `docker compose
    up` stayed degraded until it was restarted - the bug the bus already had."""

    async def answers(*_a, **_kw):
        return {}

    run(local_only.get_job("whatever"))  # fails, so the breaker closes
    assert local_only._down_until > 0.0

    monkeypatch.setattr(local_only, "DOWN_FOR", 0.0)
    monkeypatch.setattr(local_only, "_down_until", 0.0)
    run(local_only.call(answers))
    assert local_only._down_until == 0.0


# ---- all ten apps, not just the one -------------------------------------------------
#
# The claim is about the apps, plural. Only `05_debug_ceiling` was ever opened, and the
# defect that made this file necessary - a submitted job landing on a 404 - lived in the
# shared platform, so it was in all ten at once. The pages are checked for every app and
# the full submit cycle for one, because a cycle runs a real measurement and ten of them
# would put two minutes into the suite for the same answer.

APPS = sorted(p.name for p in (ROOT / "apps").iterdir() if (p / "app.py").is_file())


_LOADED: dict[str, object] = {}


def load_app(name: str):
    """Each app module, imported once per session.

    Importing one pulls in langgraph and the engine, which is most of what these tests
    cost; two tests over ten apps was twenty imports for ten apps. The app object is
    stateless between requests - its state is in Redis, or in the fallback the fixture
    clears - so sharing it across tests shares nothing that matters.
    """
    if name not in _LOADED:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            f"app_{name}", ROOT / "apps" / name / "app.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[name] = module.app
    return _LOADED[name]


def test_there_are_ten_apps_to_check():
    """A parametrised test over an empty list passes."""
    assert len(APPS) == 10, APPS


@pytest.mark.parametrize("name", APPS)
def test_every_app_serves_its_pages_with_nothing_running_behind_it(name, degraded_platform):
    """Redis, Kafka and the model all pointed at a closed port.

    `/healthz` is 503 without a model, which is right - these apps measure models, and
    one with no model to measure is not healthy. Every other page is 200, because the
    README's promise is that the demo opens.
    """
    from fastapi.testclient import TestClient

    with TestClient(load_app(name)) as client:
        for path in ("/", "/about", "/history"):
            response = client.get(path)
            assert response.status_code == 200, (name, path, response.status_code)
            assert response.text.strip(), (name, path, "empty body")
        assert client.get("/healthz").status_code == 503, name


@pytest.mark.parametrize("name", APPS)
def test_every_app_offers_a_control_someone_can_actually_set(name, degraded_platform):
    """A form with no usable control is a submit button that measures nothing.

    A `<select>` counts only if it has options: `01_localizer` chooses a repository
    from a list, and that list is built by a function that returns `[]` on any failure,
    so an empty one would render as a form with nothing to choose and no explanation.
    """
    import re

    from fastapi.testclient import TestClient

    with TestClient(load_app(name)) as client:
        page = client.get("/").text
        assert "<form" in page, name
        inputs = len(re.findall(r"<input", page))
        options = len(re.findall(r"<option", page))
        assert inputs or options, (name, "a form with nothing to set")


def test_the_repository_picker_says_why_it_is_empty():
    """`cached_repos` returns {} when data/trees is absent, rather than raising.

    So the one app whose first control is a choice rendered an empty picker and said
    nothing - a form with nothing to choose and no reason given. The hint carries the
    reason now, and carries the count when there is one.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "localizer_app", ROOT / "apps" / "01_localizer" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "no file listings found" in module._repo_hint([])
    assert "data/trees" in module._repo_hint([])
    populated = module._repo_hint([("a/b", "a/b"), ("c/d", "c/d")])
    assert populated.startswith("2 repositories")


# -- the replay window, and the partition count that was never set --------


def test_the_replay_keeps_the_most_recent_not_the_oldest():
    """It returned the OLDEST matches, for ever.

    The loop stopped at `len(out) < limit` while reading from offset 0, so the
    trailing `out[-limit:]` was a no-op. Past 200 completions for an app, "Replayed
    from the Kafka log" showed the first 200 ever and never the recent ones - on a
    topic kept for a year precisely so that old records accumulate.

    Asserted on the shape rather than against a broker, because no Kafka runs here:
    a deque with `maxlen` keeps the last N of whatever it is fed, and the loop now
    reads to the end of the log.
    """
    from collections import deque

    source = (ROOT / "apps" / "_platform" / "bus.py").read_text(encoding="utf-8")
    body = source[source.index("async def replay_completed") :]

    assert "deque" in body and "maxlen=limit" in body
    assert "while len(out) < limit" not in body, "the early stop is back"
    assert "while True:" in body
    assert "return list(window)" in body

    # The property itself, over the structure the loop uses.
    window: deque[int] = deque(maxlen=3)
    for value in range(10):
        window.append(value)
    assert list(window) == [7, 8, 9], "a maxlen deque keeps the newest"


def test_a_throwaway_replay_group_does_not_commit_offsets():
    """`/history` creates a fresh `replay-{uuid}` group on every render.

    With auto-commit on, each page view left one permanent entry in
    `__consumer_offsets` - unbounded growth from a read-only view.
    """
    source = (ROOT / "apps" / "_platform" / "bus.py").read_text(encoding="utf-8")
    assert "commit: bool = True" in source
    assert "enable_auto_commit=commit" in source

    body = source[source.index("async def replay_completed") :]
    assert "commit=False" in body, "the replay group commits again"


def test_the_broker_is_configured_for_the_partitioning_the_readme_claims():
    """`num.partitions` was unset, so Kafka's default is ONE.

    `bus.submit` keys `jobs.requested` by app name so that one app's long sweep
    occupies one partition and cannot delay another's short run, and the README's
    diagram says "partitioned by app". With one partition that is a single FIFO queue
    shared by all ten apps - the opposite of the claim, and nothing in the repository
    would have said so.
    """
    import re

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    stated = re.search(r"KAFKA_NUM_PARTITIONS:\s*(\d+)", compose)
    assert stated, "num.partitions is unset again, so the broker default is 1"

    apps = sorted(p for p in (ROOT / "apps").iterdir() if p.name[0].isdigit())
    assert int(stated.group(1)) >= len(apps), (
        f"{stated.group(1)} partitions for {len(apps)} apps: two apps would share one"
    )
    assert 'KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"' in compose, (
        "auto-created topics are what pick this count up"
    )
