"""Every implementation satisfies the port it is written against.

`agentplatform.ports` declares `Bus`, `Store` and `Cache` as `Protocol`s. A tightened
dead-code check found all three named nowhere in code - only in prose, as in
`kafka_bus.py`'s "Kafka, behind the Bus port". Structural typing means an adapter
satisfies a protocol without naming it, which is the point of it; what follows is that
nothing was checking, and a protocol nobody checks is a comment with a class statement
in front of it.

That matters here because the protocols are the contract between the in-memory
implementations every test runs against and the Redis/Kafka/Postgres adapters that
serve. `Store.delete` was added to the protocol and to both implementations in one
change; if it had been added to one, every test would still have passed and the
deployed path would have raised `AttributeError` on resubmitting a run.

Checked by signature rather than by `isinstance`: `runtime_checkable` only verifies
that the attribute exists, so it would accept a `delete` taking the wrong arguments -
and taking the wrong arguments is the realistic failure, not the method going missing.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "products" / "platform" / "src"))

from typing import Protocol  # noqa: E402

from agentplatform import ports  # noqa: E402

#: Port -> the implementations that have to satisfy it. The in-memory ones are what
#: every test runs against; the adapters are what serves.
#:
#: Keyed by the protocol itself rather than by its name, so these three classes are
#: referenced as code somewhere in the repository - which they were not. That is how
#: the dead-code check found them: structural typing means an adapter never has to
#: name the port it satisfies, so all three were mentioned only in prose.
IMPLEMENTATIONS: dict[type, tuple[str, ...]] = {
    ports.Bus: ("InMemoryBus", "adapters.kafka_bus.KafkaBus"),
    ports.Store: ("InMemoryStore", "adapters.postgres_store.PostgresStore"),
    ports.Cache: ("InMemoryCache", "adapters.redis_cache.RedisCache"),
}


def _resolve(name: str):
    if "." not in name:
        return getattr(ports, name, None)
    module_path, _, attr = name.rpartition(".")
    import importlib

    try:
        module = importlib.import_module(f"agentplatform.{module_path}")
    except Exception:  # pragma: no cover - an adapter whose driver is absent
        return None
    return getattr(module, attr, None)


def _protocol_methods(protocol) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in vars(protocol).items()
        if callable(member) and not name.startswith("_")
    }


def test_every_port_has_implementations_named():
    """A sweep over an empty mapping passes, and there are three ports."""
    # `Protocol` itself is imported into the module and is a protocol, so it is
    # excluded by identity rather than by name - an exclusion by name would also drop
    # a port someone called Protocol.
    declared = {
        name
        for name, value in vars(ports).items()
        if isinstance(value, type)
        and getattr(value, "_is_protocol", False)
        and value is not Protocol
    }
    assert declared == {p.__name__ for p in IMPLEMENTATIONS}, sorted(declared)
    for port, implementations in IMPLEMENTATIONS.items():
        assert implementations, port.__name__


CASES = [
    (port, impl)
    for port, implementations in sorted(IMPLEMENTATIONS.items(), key=lambda kv: kv[0].__name__)
    for impl in implementations
]


@pytest.mark.parametrize("port,impl", CASES, ids=[f"{p.__name__}<-{i}" for p, i in CASES])
def test_the_implementation_has_every_method_the_port_declares(port: type, impl: str):
    protocol = port
    implementation = _resolve(impl)
    if implementation is None:
        pytest.skip(f"{impl} is not importable here")

    required = _protocol_methods(protocol)
    assert required, f"{port.__name__} declares no methods"

    missing = [name for name in required if not callable(getattr(implementation, name, None))]
    assert not missing, f"{impl} does not implement {missing} from {port.__name__}"


@pytest.mark.parametrize("port,impl", CASES, ids=[f"{p.__name__}<-{i}" for p, i in CASES])
def test_the_implementation_takes_the_arguments_the_port_declares(port: type, impl: str):
    """The realistic failure: a method that exists and takes something else.

    `runtime_checkable` would pass an implementation whose `delete(self, key)` dropped
    the table argument, and every caller written against the port would then be wrong
    in a way no test running against the in-memory one could see.
    """
    protocol = port
    implementation = _resolve(impl)
    if implementation is None:
        pytest.skip(f"{impl} is not importable here")

    wrong = []
    for name, expected in _protocol_methods(protocol).items():
        actual = inspect.signature(getattr(implementation, name))
        want = [p for p in expected.parameters if p != "self"]
        have = {p: q for p, q in actual.parameters.items() if p != "self"}

        # Every parameter the port declares, in the port's order, so a caller written
        # against the port can pass them positionally.
        shared = [p for p in have if p in want]
        if shared != want:
            wrong.append(f"{name}: port takes {want}, {impl} takes {list(have)}")
            continue
        # An implementation may take MORE - `KafkaBus.poll` has a `timeout_s` the
        # in-memory bus has no use for - as long as the extra is optional. A required
        # extra parameter means a caller written against the port cannot call it.
        required_extra = [
            p
            for p, q in have.items()
            if p not in want
            and q.default is inspect.Parameter.empty
            and q.kind not in (q.VAR_POSITIONAL, q.VAR_KEYWORD)
        ]
        if required_extra:
            wrong.append(
                f"{name}: {impl} requires {required_extra}, which {port.__name__} does not declare"
            )
    assert not wrong, wrong


def test_the_ports_module_is_now_referenced_by_this_file():
    """The dead-code check reads uses from code with prose stripped, so this file is
    what makes the three protocol names referenced at all. Stated outright, because a
    test whose only purpose a reader cannot see is the next thing to be deleted."""
    source = Path(__file__).read_text(encoding="utf-8")
    for port in IMPLEMENTATIONS:
        assert f"ports.{port.__name__}" in source, port.__name__
