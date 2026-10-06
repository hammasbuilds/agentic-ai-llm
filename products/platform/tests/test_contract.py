"""One set of assertions, run against the in-memory ports and against the real ones.

The real implementations are skipped when the service is not up, so this file is
green on a laptop with nothing running and meaningful on a machine with
``docker compose up``. A contract test that only ever runs against a fake is a
test of the fake.
"""

from __future__ import annotations

import os

import pytest

from agentplatform.adapters import KafkaBus, PostgresStore, RedisCache
from agentplatform.ports import InMemoryBus, InMemoryCache, InMemoryStore

KAFKA = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
REDIS = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
POSTGRES = os.environ.get("POSTGRES_DSN", "postgresql://agent:agent@127.0.0.1:5432/agent")


def _topic(name: str) -> str:
    return f"contract-{name}-{os.getpid()}"


# ------------------------------------------------------------------ cache


def caches():
    yield pytest.param(InMemoryCache(), id="in-memory")
    real = RedisCache(REDIS)
    yield pytest.param(
        real,
        id="redis",
        marks=pytest.mark.skipif(not (seen := real.probe()), reason=seen.reason),
    )


@pytest.fixture(params=list(caches()))
def cache(request):
    return request.param


def test_a_value_survives_a_round_trip(cache):
    cache.set("contract:v", "1")
    assert cache.get("contract:v") == "1"
    cache.delete("contract:v")


def test_a_missing_key_is_none_not_an_error(cache):
    assert cache.get("contract:absent") is None


def test_add_is_the_lock_primitive(cache):
    cache.delete("contract:lock")
    assert cache.add("contract:lock", "worker-a", 60) is True
    assert cache.add("contract:lock", "worker-b", 60) is False
    cache.delete("contract:lock")
    assert cache.add("contract:lock", "worker-b", 60) is True
    cache.delete("contract:lock")


# ------------------------------------------------------------------ store


def stores():
    yield pytest.param(InMemoryStore(), id="in-memory")
    real = PostgresStore(POSTGRES)
    yield pytest.param(
        real,
        id="postgres",
        marks=pytest.mark.skipif(not (seen := real.probe()), reason=seen.reason),
    )


@pytest.fixture(params=list(stores()))
def store(request):
    return request.param


def test_a_row_survives_a_round_trip(store):
    store.put("contract", "r1", {"status": "done", "n": 2})
    assert store.get("contract", "r1") == {"status": "done", "n": 2}


def test_a_put_replaces_rather_than_duplicating(store):
    store.put("contract", "r2", {"n": 1})
    store.put("contract", "r2", {"n": 2})
    assert store.get("contract", "r2") == {"n": 2}
    assert len([r for r in store.rows("contract") if r.get("n") == 2]) >= 1


def test_a_missing_row_is_none(store):
    assert store.get("contract", "never-written") is None


# ------------------------------------------------------------------ bus


def buses():
    yield pytest.param(InMemoryBus(), id="in-memory")
    real = KafkaBus(KAFKA)
    yield pytest.param(
        real,
        id="kafka",
        marks=pytest.mark.skipif(not (seen := real.probe()), reason=seen.reason),
    )


@pytest.fixture(params=list(buses()))
def bus(request):
    return request.param


def test_messages_for_one_key_arrive_in_order(bus):
    topic = _topic("order")
    for n in range(5):
        bus.publish(topic, "deal:4192", {"n": n})
    got = bus.poll(topic, "contract-workers", limit=10)
    assert [m.value["n"] for m in got] == [0, 1, 2, 3, 4]


def test_one_key_always_lands_on_one_partition(bus):
    topic = _topic("partition")
    first = bus.publish(topic, "deal:4192", {"n": 1})
    second = bus.publish(topic, "deal:4192", {"n": 2})
    assert first.partition == second.partition


def test_two_groups_read_the_same_topic_independently(bus):
    topic = _topic("groups")
    bus.publish(topic, "deal:1", {"n": 1})
    assert len(bus.poll(topic, "contract-a", limit=10)) == 1
    assert len(bus.poll(topic, "contract-b", limit=10)) == 1


# ------------------------------------------------------------------ the skips


def test_a_skipped_adapter_names_the_cause_rather_than_blaming_the_service():
    """Every skip above used to read like the service was down.

    All three probes caught `Exception` and answered a bare False, so a missing
    client library and an unreachable service were the same answer - and the reasons
    said "no broker on localhost:9092" and "no postgres" either way. On this machine
    the `infra` extra declared `confluent-kafka` while the adapter imports `kafka`,
    so the Kafka contract tests skipped for a reason that sent anyone reading them to
    look at the wrong thing.
    """
    from agentplatform.adapters.probe import NO_CLIENT, OK, UNREACHABLE

    for adapter in (RedisCache(REDIS), PostgresStore(POSTGRES), KafkaBus(KAFKA)):
        seen = adapter.probe()
        assert seen.status in {OK, NO_CLIENT, UNREACHABLE}
        if seen.status == OK:
            assert seen.reason == ""
            continue
        assert seen.reason, f"{type(adapter).__name__} skipped with no reason"
        if seen.status == NO_CLIENT:
            # Names the package to install, and does not mention a host or port.
            assert "pip install" in seen.reason
            assert "is not installed" in seen.reason
        else:
            # Names the target it could not reach, and the error class.
            assert "(" in seen.reason and ")" in seen.reason


def test_the_declared_infra_extra_is_the_client_the_adapter_imports():
    """`confluent-kafka` was declared and `kafka` imported, which cannot both work."""
    import re
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    infra = declared["project"]["optional-dependencies"]["infra"]
    names = {re.split(r"[" + chr(92) + "[><=;]", d, maxsplit=1)[0].strip() for d in infra}

    source = (root / "src" / "agentplatform" / "adapters" / "kafka_bus.py").read_text(
        encoding="utf-8"
    )
    assert "from kafka import" in source
    assert "kafka-python" in names, f"adapter imports `kafka`, infra declares {sorted(names)}"
    assert "confluent-kafka" not in names
