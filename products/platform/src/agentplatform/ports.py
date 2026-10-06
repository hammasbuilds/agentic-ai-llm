"""The bus, the store and the cache, as ports with in-memory implementations.

Kafka, Postgres and Redis are the deployment targets. Everything above them is
written against these three protocols, which is why a product runs end to end in
a test with no broker, no database and no container.

The in-memory bus is not a stub. It partitions by key using the same function
the real one will, so per-entity ordering is demonstrated rather than assumed.
"""

from __future__ import annotations

import threading
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
    def commit(self, topic: str, group: str, offsets: dict | None = None) -> None: ...
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
    """Partitioned, ordered, replayable, and at-least-once.

    The last one is why there are two cursors rather than one. `poll` used to move
    the committed offset itself, which made `commit` decorative - the Bus protocol
    declared it and nothing in the repository called it - and meant a worker that
    crashed after polling and before finishing had lost the message. That is
    at-most-once delivery wearing a commit method.

    `position` is how far a running consumer has read. `committed` is how far it has
    acknowledged. A restart resumes from `committed`, so an unacknowledged message is
    delivered again.
    """

    partitions: int = 12
    _log: dict = field(default_factory=dict)  # (topic, partition) -> [Message]
    #: How far this consumer has read. Advanced by poll.
    _offsets: dict = field(default_factory=dict)  # (topic, group, partition) -> next offset
    #: How far this consumer has acknowledged. Advanced only by commit.
    _committed: dict = field(default_factory=dict)  # (topic, group, partition) -> next offset

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

    def commit(self, topic: str, group: str, offsets: dict | None = None) -> None:
        """Acknowledge. Without this, a restart redelivers.

        Given no offsets, it acknowledges everything polled so far, which is what a
        worker finishing a batch means. Given offsets, it acknowledges exactly those
        partitions - which is how a worker that handled part of a batch keeps the
        rest redeliverable.
        """
        if offsets is None:
            for (t, g, partition), offset in list(self._offsets.items()):
                if (t, g) == (topic, group):
                    self._committed[(topic, group, partition)] = offset
            return
        for partition, offset in offsets.items():
            self._committed[(topic, group, partition)] = offset
            # Reading cannot lag behind acknowledgement.
            held = self._offsets.get((topic, group, partition), 0)
            self._offsets[(topic, group, partition)] = max(held, offset)

    def restart(self, topic: str, group: str) -> None:
        """What a crashed and restarted worker sees: everything not acknowledged.

        A consumer group's position is process state; its committed offset is not.
        This drops the first and keeps the second, which is the only way to observe
        whether delivery is at-least-once or at-most-once.
        """
        for key in [k for k in self._offsets if k[0] == topic and k[1] == group]:
            self._offsets[key] = self._committed.get(key, 0)

    def rewind(self, topic: str, group: str) -> None:
        """Replay from the beginning. The reason the events topic is the audit log."""
        for key in [k for k in self._offsets if k[0] == topic and k[1] == group]:
            self._offsets[key] = 0
            self._committed[key] = 0

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
        """Unacknowledged messages, which is the number that matters on a restart.

        Measured against the read position it under-reported: a batch polled and not
        yet committed counted as caught up, so lag read zero while the work was still
        outstanding and would be redelivered.
        """
        total = 0
        for (t, partition), log in self._log.items():
            if t == topic:
                total += len(log) - self._committed.get((topic, group, partition), 0)
        return total

    def in_flight(self, topic: str, group: str) -> int:
        """Polled and not yet acknowledged."""
        total = 0
        for (t, g, partition), read in self._offsets.items():
            if (t, g) == (topic, group):
                total += read - self._committed.get((topic, group, partition), 0)
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
    """Redis-shaped, including the one operation locking depends on.

    `add` is guarded, because it is a lock and the products that use it run several
    threads against one of these. It was a bare `if key in values: ... values[key] =`
    - two operations with a thread switch possible between them, so two agents could
    both be told they held the same lock. I could not provoke that on this CPython
    build in 400 trials of eight contending threads with the switch interval at a
    nanosecond, which is the point: it was correct by an implementation detail of the
    GIL rather than by construction, and swarm-lab's "work is done exactly once at
    every N" rests on it whenever Redis is not up.
    """

    _values: dict = field(default_factory=dict)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        with self._guard:
            self._values[key] = value

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """SET NX. Returns False when the key is already held — this is the lock."""
        with self._guard:
            if key in self._values:
                return False
            self._values[key] = value
            return True

    def delete(self, key: str) -> None:
        with self._guard:
            self._values.pop(key, None)
