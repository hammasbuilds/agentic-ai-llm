"""The Kafka side with a broker that answers.

Same gap as `tests/test_platform_up.py` and the same reason: no CI runner here has a
broker, so every assertion about `apps/_platform/bus.py` was about what it does when
`producer()` returns `None`. `submit` returning `(job_id, False)` was covered from four
directions; `submit` actually publishing was covered from none, and neither was the
windowing in `replay_completed` - the function whose bug was returning the *oldest* two
hundred completions under a heading that said "Replayed from the Kafka log".

There is no in-process Kafka the way `fakeredis` is an in-process Redis, so the producer
and consumer are stood in for here. That is a narrower claim than the Redis tests make
and it is worth being explicit about what it does and does not cover: the event shapes,
the partition key, and the windowing are this module's own logic and are checked. Broker
behaviour - partition assignment, offset commit, delivery semantics - is not, and no
test here should be read as evidence about it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._platform import bus  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeProducer:
    """Records what would have been published, in order."""

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, dict, str]] = []
        self.waited: list[str] = []
        self.fail = fail

    async def send(self, topic, value, key=None):
        if self.fail:
            raise bus.KafkaError("broker gone")
        self.sent.append((topic, value, key))

    async def send_and_wait(self, topic, value, key=None):
        if self.fail:
            raise bus.KafkaError("broker gone")
        self.sent.append((topic, value, key))
        self.waited.append(topic)


@pytest.fixture
def producer(monkeypatch):
    fake = FakeProducer()

    async def _producer():
        return fake

    monkeypatch.setattr(bus, "producer", _producer)
    return fake


# -- submit --------------------------------------------------------------------


def test_submit_publishes_the_request_and_says_it_went_through(producer):
    job_id, via_kafka = run(bus.submit("debug-ceiling", {"limit": 50}))

    assert via_kafka is True
    assert len(job_id) == 12
    topic, event, key = producer.sent[0]
    assert topic == bus.TOPIC_REQUESTED
    assert event["job_id"] == job_id
    assert event["app"] == "debug-ceiling"
    assert event["params"] == {"limit": 50}
    assert isinstance(event["requested_at"], float)


def test_submit_keys_by_app_so_one_sweep_does_not_reorder_another(producer):
    """The partition key is the whole reason `KAFKA_NUM_PARTITIONS: 10` is in compose.

    Ten apps on one broker with the default of one partition shared a single FIFO
    queue; ten partitions only help if the key spreads the apps across them. Nothing
    asserted the key, so a `key=None` would have left the claim in the README true in
    configuration and false in code.
    """
    run(bus.submit("a", {}))
    run(bus.submit("b", {}))
    assert [key for _, _, key in producer.sent] == ["a", "b"]


def test_submit_waits_for_the_broker_rather_than_firing_and_forgetting(producer):
    """`send_and_wait`, not `send`.

    A submit that returns `True` before the broker has the record would tell the user
    the run is queued when it may not be. Progress ticks are the opposite case and are
    deliberately fire-and-forget.
    """
    run(bus.submit("a", {}))
    assert producer.waited == [bus.TOPIC_REQUESTED]


def test_a_broker_error_mid_publish_is_reported_not_raised(monkeypatch):
    """The inline-runner fallback depends on this returning `False`, not throwing."""
    fake = FakeProducer(fail=True)

    async def _producer():
        return fake

    monkeypatch.setattr(bus, "producer", _producer)
    job_id, via_kafka = run(bus.submit("a", {}))
    assert via_kafka is False
    assert len(job_id) == 12


# -- progress and completion ---------------------------------------------------


def test_a_progress_tick_carries_both_numbers_and_the_app_key(producer):
    run(bus.emit_progress("j1", "a", done=43, total=250, note="repairing"))

    topic, event, key = producer.sent[0]
    assert topic == bus.TOPIC_PROGRESS
    assert (event["done"], event["total"], event["note"]) == (43, 250, "repairing")
    assert (event["job_id"], event["app"], key) == ("j1", "a", "a")


def test_a_progress_tick_does_not_wait_for_the_broker(producer):
    """Fire-and-forget on purpose: a slow broker must not slow the measurement."""
    run(bus.emit_progress("j1", "a", 1, 2))
    assert producer.waited == []


def test_a_completion_waits_for_the_broker(producer):
    """This one is the durable record, so losing it loses the run's result."""
    run(bus.emit_completed("j1", "a", {"score": 0.5}))

    topic, event, key = producer.sent[0]
    assert topic == bus.TOPIC_COMPLETED
    assert event["result"] == {"score": 0.5}
    assert key == "a"
    assert producer.waited == [bus.TOPIC_COMPLETED]


# -- replay, which is the claim that justifies a log over a queue ---------------


class FakeRecord:
    def __init__(self, value):
        self.value = value


class FakeConsumer:
    """Hands out one batch per `getmany`, then an empty one to end the loop."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, timeout_ms=0, max_records=0):
        if not self.batches:
            return {}
        return {"p0": [FakeRecord(v) for v in self.batches.pop(0)]}


def _replay(monkeypatch, batches, **kwargs):
    fake = FakeConsumer(batches)
    monkeypatch.setattr(bus, "consumer", lambda *a, **k: fake)
    return run(bus.replay_completed(**kwargs)), fake


def test_replay_returns_the_newest_completions_not_the_oldest(monkeypatch):
    """The bug this function had, pinned.

    It read from offset zero and stopped once it had `limit` records, so `out[-limit:]`
    was a no-op: past 200 completions for an app, `/history` showed the first 200 ever
    recorded and never a recent run. A deque with `maxlen` reads to the end of the log
    and keeps the tail.
    """
    log = [[{"app": "a", "n": n} for n in range(10)]]
    out, _ = _replay(monkeypatch, log, limit=3)
    assert [r["n"] for r in out] == [7, 8, 9]


def test_replay_reads_the_whole_log_even_when_the_window_filled_early(monkeypatch):
    """Across batches, so the early return cannot hide behind one big batch."""
    log = [[{"app": "a", "n": 0}, {"app": "a", "n": 1}], [{"app": "a", "n": 2}]]
    out, consumer = _replay(monkeypatch, log, limit=2)
    assert [r["n"] for r in out] == [1, 2]
    assert consumer.batches == []  # it did not stop early


def test_replay_filters_by_app_before_windowing(monkeypatch):
    """Otherwise the window fills with another app's runs and returns too few.

    Filtering after the window would give this one record for app `a`, not three.
    """
    log = [[{"app": "b", "n": n} for n in range(10)] + [{"app": "a", "n": 99}]]
    out, _ = _replay(monkeypatch, log, app="a", limit=3)
    assert [r["n"] for r in out] == [99]


def test_replay_without_an_app_returns_every_app(monkeypatch):
    log = [[{"app": "a", "n": 1}, {"app": "b", "n": 2}]]
    out, _ = _replay(monkeypatch, log, limit=10)
    assert [r["app"] for r in out] == ["a", "b"]


def test_replay_stops_the_consumer_even_on_the_happy_path(monkeypatch):
    """A fresh `replay-{uuid}` group per page render: not stopping leaks a client."""
    _, consumer = _replay(monkeypatch, [[{"app": "a"}]], limit=1)
    assert consumer.started and consumer.stopped


def test_replay_of_an_empty_log_is_an_empty_list(monkeypatch):
    out, _ = _replay(monkeypatch, [], limit=10)
    assert out == []
