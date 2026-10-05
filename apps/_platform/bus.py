"""Kafka: the job queue and the event log.

The UI never runs a measurement. It publishes a request to `jobs.requested` and returns
immediately; a worker consumes the partition, runs the job, and publishes ticks to
`jobs.progress` and a final record to `jobs.completed`. The browser watches Redis pub/sub
for the ticks.

Why a log rather than a task queue. These runs take minutes and produce a stream of partial
results, and three properties fall out of Kafka that a simple queue does not give:

- **Replay.** `jobs.completed` is the durable record of every measurement ever run here.
  Re-reading the topic from offset zero rebuilds the results database without re-running a
  single generation, which matters when a run costs an hour of GPU.
- **Fan-out.** The same completion event feeds the app's own results page, the cross-app
  dashboard and the metrics roll-up, with no app knowing about the others.
- **Back-pressure that is honest.** One GPU means one worker. Partitioning by app keeps a
  long sweep from starving a short one, and the queue depth is visible rather than implied.

Degrades deliberately: if Kafka is unreachable the app falls back to running the job in a
background task in-process. That path is slower and loses replay, and the UI says so rather
than pretending the bus is there.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from contextlib import suppress
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")

TOPIC_REQUESTED = "jobs.requested"
TOPIC_PROGRESS = "jobs.progress"
TOPIC_COMPLETED = "jobs.completed"

_producer: AIOKafkaProducer | None = None
_available: bool | None = None
# When the last failed attempt was, so an unreachable bus is not retried on every
# request and is not written off for the life of the process either. `docker compose up`
# after starting an app is the normal sequence, and before this the app stayed degraded
# until it was restarted.
_last_attempt: float = 0.0
RETRY_AFTER = float(os.environ.get("BUS_RETRY_AFTER", "30"))
# A bounded first attempt. An absent broker costs the operating system's full TCP
# connect timeout - about four seconds here - and that is paid by whoever opens the page.
START_TIMEOUT = float(os.environ.get("BUS_START_TIMEOUT", "1.5"))


async def producer() -> AIOKafkaProducer | None:
    """The shared producer, or None if the bus is not reachable."""
    global _producer, _available, _last_attempt
    if _producer is not None:
        return _producer
    if _available is False and (time.monotonic() - _last_attempt) < RETRY_AFTER:
        return None
    _last_attempt = time.monotonic()
    try:
        p = AIOKafkaProducer(
            bootstrap_servers=BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            # A measurement request is worth waiting for an ack; there are tens of these
            # per hour, not thousands per second.
            acks="all",
            request_timeout_ms=10_000,
        )
        await asyncio.wait_for(p.start(), timeout=START_TIMEOUT)
        _producer, _available = p, True
        return p
    except (KafkaError, OSError, AssertionError, TimeoutError):
        # Close the half-started client. aiokafka allocates its sender and connection
        # objects in the constructor, so a failed start leaves them for the garbage
        # collector to complain about: booting any app with no broker printed
        # "Unclosed AIOKafkaProducer" on every request, which is both noise in the
        # window someone is watching and a real socket left to time out.
        with contextlib.suppress(Exception):
            await p.stop()
        _available = False
        return None


async def close() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def available() -> bool:
    return (await producer()) is not None


async def submit(app: str, params: dict[str, Any]) -> tuple[str, bool]:
    """Publish a job request. Returns (job_id, went_through_kafka)."""
    job_id = uuid.uuid4().hex[:12]
    event = {
        "job_id": job_id,
        "app": app,
        "params": params,
        "requested_at": time.time(),
    }
    p = await producer()
    if p is None:
        return job_id, False
    try:
        # Key by app so one app's long sweep occupies one partition and does not
        # reorder another app's short run.
        await p.send_and_wait(TOPIC_REQUESTED, event, key=app)
        return job_id, True
    except KafkaError:
        return job_id, False


async def emit_progress(job_id: str, app: str, done: int, total: int, note: str = "") -> None:
    p = await producer()
    if p is None:
        return
    with suppress(KafkaError):
        await p.send(
            TOPIC_PROGRESS,
            {
                "job_id": job_id,
                "app": app,
                "done": done,
                "total": total,
                "note": note,
                "at": time.time(),
            },
            key=app,
        )


async def emit_completed(job_id: str, app: str, result: dict) -> None:
    p = await producer()
    if p is None:
        return
    with suppress(KafkaError):
        await p.send_and_wait(
            TOPIC_COMPLETED,
            {"job_id": job_id, "app": app, "result": result, "at": time.time()},
            key=app,
        )


def consumer(topic: str, group: str, from_beginning: bool = False) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=group,
        value_deserializer=lambda v: json.loads(v.decode()),
        # `earliest` is what makes the completed topic a replayable results database
        # rather than a notification stream.
        auto_offset_reset="earliest" if from_beginning else "latest",
        enable_auto_commit=True,
    )


async def replay_completed(app: str | None = None, limit: int = 200) -> list[dict]:
    """Rebuild results from the log, without re-running anything.

    This is the property that justifies a log over a queue: an hour of GPU time is
    recoverable from `jobs.completed` after any crash, redeploy or schema change.
    """
    out: list[dict] = []
    c = consumer(TOPIC_COMPLETED, group=f"replay-{uuid.uuid4().hex[:8]}", from_beginning=True)
    try:
        await c.start()
    except (KafkaError, OSError, AssertionError):
        with contextlib.suppress(Exception):
            await c.stop()  # same half-started client as the producer above
        return out
    try:
        while len(out) < limit:
            batch = await c.getmany(timeout_ms=1500, max_records=100)
            if not batch:
                break
            for records in batch.values():
                for rec in records:
                    if app is None or rec.value.get("app") == app:
                        out.append(rec.value)
    finally:
        await c.stop()
    return out[-limit:]
