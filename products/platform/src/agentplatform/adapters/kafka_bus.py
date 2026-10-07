"""Kafka, behind the Bus port.

Two things here are not incidental:

- **The key is the partition key**, and it is the entity id. Per-entity ordering
  is what stops two agents processing one deal out of order, and it is free only
  if every producer uses the same key.
- **Auto-commit is off.** A worker that crashes mid-generation must redeliver,
  not skip. At-least-once plus the idempotency key in Redis is the combination;
  auto-commit turns it into at-most-once silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..ports import Message
from .probe import Probe
from .probe import probe as probe_target


@dataclass
class KafkaBus:
    bootstrap: str = "localhost:9092"
    _producer: object = field(default=None, repr=False)
    _consumers: dict = field(default_factory=dict, repr=False)
    _buffer: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------- clients

    def producer(self):
        if self._producer is None:
            from kafka import KafkaProducer  # noqa: PLC0415 — optional extra

            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap,
                key_serializer=lambda k: k.encode("utf-8"),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
            )
        return self._producer

    def consumer(self, topic: str, group: str, ready_timeout_s: float = 20.0):
        """A consumer that is actually ready to read.

        Three steps, none of which are optional and all of which are easy to
        skip:

        1. wait for the topic to appear in cluster metadata — a topic the
           producer created moments ago is not instantly visible to a consumer;
        2. subscribe;
        3. poll until the coordinator has assigned partitions.

        Skipping step 3 makes a first-run worker read nothing and commit, which
        looks exactly like an empty queue.
        """
        import time  # noqa: PLC0415

        key = (topic, group)
        if key in self._consumers:
            return self._consumers[key]

        from kafka import KafkaConsumer  # noqa: PLC0415 — optional extra

        consumer = KafkaConsumer(
            bootstrap_servers=self.bootstrap,
            group_id=group,
            auto_offset_reset="earliest",
            # Off on purpose. See the module docstring.
            enable_auto_commit=False,
            key_deserializer=lambda k: k.decode("utf-8") if k else "",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )

        deadline = time.monotonic() + ready_timeout_s
        while time.monotonic() < deadline and topic not in consumer.topics():
            time.sleep(0.2)

        consumer.subscribe([topic])
        # Polling is the only way to make the coordinator assign partitions, and
        # a poll that assigns can also FETCH. Throwing those records away is how
        # the first batch silently disappears — assignment succeeds, messages
        # gone. Keep them.
        stash = self._buffer.setdefault(key, [])
        while time.monotonic() < deadline and not consumer.assignment():
            for records in consumer.poll(timeout_ms=300).values():
                stash.extend(
                    Message(topic, r.key, r.value, r.partition, r.offset) for r in records
                )

        self._consumers[key] = consumer
        return consumer

    # ------------------------------------------------------------- the port

    def publish(self, topic: str, key: str, value: dict) -> Message:
        future = self.producer().send(topic, key=key, value=value)
        meta = future.get(timeout=10)
        self.producer().flush()
        return Message(topic, key, dict(value), meta.partition, meta.offset)

    def poll(
        self, topic: str, group: str, limit: int = 10, timeout_s: float = 8.0
    ) -> list[Message,]:
        """Fetch up to ``limit`` messages, waiting for group assignment first.

        A brand-new consumer group returns nothing on its first poll while the
        coordinator is still assigning partitions. Returning that empty batch as
        "no messages" is wrong and is the bug this loop fixes: a first-run
        worker would silently process nothing and commit.
        """
        import time  # noqa: PLC0415

        consumer = self.consumer(topic, group)
        deadline = time.monotonic() + timeout_s
        # Anything the readiness polls already fetched comes first.
        out: list[Message] = self._buffer.pop((topic, group), [])
        while len(out) < limit and time.monotonic() < deadline:
            batches = consumer.poll(timeout_ms=500, max_records=limit)
            for records in batches.values():
                for record in records:
                    out.append(
                        Message(
                            topic,
                            record.key,
                            record.value,
                            record.partition,
                            record.offset,
                        )
                    )
            if out:
                break
            if not consumer.assignment():
                continue  # still joining the group; not the same as "empty"
        out.sort(key=lambda m: (m.partition, m.offset))
        return out[:limit]

    def commit(self, topic: str, group: str, offsets: dict | None = None) -> None:
        """Acknowledge, for every assigned partition or for the named ones only.

        The `offsets` argument used to be accepted and discarded: the call was
        `consumer.commit()` whatever was passed, which acknowledges the consumer's
        whole position. A worker handing back a partial acknowledgement - the one
        partition it finished - therefore acknowledged the entire batch, and the rest
        of it was never redelivered. Silent message loss, from an argument that
        looked honoured because the signature named it.
        """
        consumer = self.consumer(topic, group)
        if offsets is None:
            consumer.commit()
            return
        from kafka import OffsetAndMetadata, TopicPartition  # noqa: PLC0415 — optional extra

        consumer.commit(
            {
                TopicPartition(topic, int(partition)): OffsetAndMetadata(int(offset), "", -1)
                for partition, offset in offsets.items()
            }
        )

    def rewind(self, topic: str, group: str) -> None:
        consumer = self.consumer(topic, group)
        consumer.poll(timeout_ms=100)
        consumer.seek_to_beginning()

    def lag(self, topic: str, group: str) -> int:
        consumer = self.consumer(topic, group)
        consumer.poll(timeout_ms=100)
        assigned = consumer.assignment()
        if not assigned:
            return 0
        ends = consumer.end_offsets(list(assigned))
        return sum(ends[tp] - consumer.position(tp) for tp in assigned)

    def tail(self, topic: str, limit: int = 20) -> list[Message]:
        """Recent messages without consuming them, on a throwaway group."""
        import uuid  # noqa: PLC0415

        group = f"tail-{uuid.uuid4().hex[:8]}"
        try:
            return self.poll(topic, group, limit=limit)
        finally:
            consumer = self._consumers.pop((topic, group), None)
            if consumer is not None:
                consumer.close()

    def close(self) -> None:
        for consumer in self._consumers.values():
            consumer.close()
        self._consumers.clear()
        if self._producer is not None:
            self._producer.close()
            self._producer = None

    def probe(self) -> Probe:
        """Verify, rather than assume. Constructing a producer is not proof.

        Returns *why*, not just whether: this adapter imports `kafka-python` and the
        `infra` extra declared `confluent-kafka`, so the common failure here was a
        missing client library reported as a missing broker.
        """

        def contact() -> bool:
            producer = self.producer()
            return bool(
                producer.partitions_for("__reachability_probe")
                or producer.bootstrap_connected()
            )

        return probe_target(self.bootstrap, contact, requires="kafka-python")

    def reachable(self) -> bool:
        """Kept for callers that only want the boolean."""
        return bool(self.probe())


if TYPE_CHECKING:  # pragma: no cover - checked by a type checker, not at runtime
    # `KafkaBus` satisfies `Bus` structurally, which is why nothing said so
    # until this line: the port was named in this file's docstring and in no
    # code anywhere. A method added to `Bus` and not here is now a type
    # error rather than an `AttributeError` on the deployed path.
    from ..ports import Bus

    _satisfies: Bus = KafkaBus()
