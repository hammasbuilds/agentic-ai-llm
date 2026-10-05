"""The bus, the store and the cache, as ports with in-memory implementations.

Kafka, Postgres and Redis are the deployment targets. Everything above them is
written against these three protocols, which is why a product runs end to end in
a test with no broker, no database and no container.

The in-memory bus is not a stub. It partitions by key using the same function
the real one will, so per-entity ordering is demonstrated rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import topics as _topics


@dataclass(frozen=True)
class Message:
    topic: str
    key: str
    value: dict
    partition: int
    offset: int


class Bus(Protocol):
    def publish(self, topic: str, key: str, value: dict) -> Message: ...
    def poll(self, topic: str, group: str, limit: int = 10) -> list[Message]: ...
    def commit(self, topic: str, group: str, offsets: dict) -> None: ...
    def tail(self, topic: str, limit: int = 20) -> list[Message]: ...


class Store(Protocol):
    def put(self, table: str, key: str, row: dict) -> None: ...
    def get(self, table: str, key: str) -> dict | None: ...
    def rows(self, table: str) -> list[dict]: ...


class Cache(Protocol):
    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...
    def get(self, key: str) -> str | None: ...
    def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool: ...


@dataclass
class InMemoryBus:
    """Partitioned, ordered, replayable. The three properties that matter."""

    partitions: int = 12
    _log: dict = field(default_factory=dict)  # (topic, partition) -> [Message]
    _offsets: dict = field(default_factory=dict)  # (topic, group, partition) -> next offset

    def publish(self, topic: str, key: str, value: dict) -> Message:
        partition = _topics.partition_for(key, self.partitions)
        log = self._log.setdefault((topic, partition), [])
        message = Message(topic, key, dict(value), partition, len(log))
        log.append(message)
        return message

    def poll(self, topic: str, group: str, limit: int = 10) -> list[Message]:
        out: list[Message] = []
        for (t, partition), log in sorted(self._log.items()):
            if t != topic:
                continue
            cursor = self._offsets.get((topic, group, partition), 0)
            while cursor < len(log) and len(out) < limit:
                out.append(log[cursor])
                cursor += 1
            self._offsets[(topic, group, partition)] = cursor
        return out

    def commit(self, topic: str, group: str, offsets: dict) -> None:
        for partition, offset in offsets.items():
            self._offsets[(topic, group, partition)] = offset

    def rewind(self, topic: str, group: str) -> None:
        """Replay from the beginning. The reason the events topic is the audit log."""
        for key in [k for k in self._offsets if k[0] == topic and k[1] == group]:
            self._offsets[key] = 0

    def tail(self, topic: str, limit: int = 20) -> list[Message]:
        """The most recent messages, without consuming them.

        The console reads the event feed; it must not steal messages from the
        projector that is also reading it.
        """
        out: list[Message] = []
        for (t, _partition), log in sorted(self._log.items()):
            if t == topic:
                out.extend(log)
        out.sort(key=lambda m: (m.partition, m.offset))
        return out[-limit:]

    def lag(self, topic: str, group: str) -> int:
        total = 0
        for (t, partition), log in self._log.items():
            if t == topic:
                total += len(log) - self._offsets.get((topic, group, partition), 0)
        return total


@dataclass
class InMemoryStore:
    _tables: dict = field(default_factory=dict)

    def put(self, table: str, key: str, row: dict) -> None:
        self._tables.setdefault(table, {})[key] = dict(row)

    def get(self, table: str, key: str) -> dict | None:
        found = self._tables.get(table, {}).get(key)
        return dict(found) if found is not None else None

    def rows(self, table: str) -> list[dict]:
        return [dict(r) for _, r in sorted(self._tables.get(table, {}).items())]


@dataclass
class InMemoryCache:
    """Redis-shaped, including the one operation locking depends on."""

    _values: dict = field(default_factory=dict)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        self._values[key] = value

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """SET NX. Returns False when the key is already held — this is the lock."""
        if key in self._values:
            return False
        self._values[key] = value
        return True

    def delete(self, key: str) -> None:
        self._values.pop(key, None)
