"""Redis: the generation cache, job state, and the live progress channel.

Three jobs, and none of them is decorative.

**Generation cache.** Every one of these apps asks the same model the same questions -
project 04 and project 01 send an identical first-attempt prompt to all 250 MBPP tasks.
Keyed on `(model, prompt, temperature, seed)`, the second app pays nothing. On a single
GPU that is the difference between a demo you can click through and one you have to wait
for. The file-based cache this replaces did the same thing for one process; Redis does it
across ten apps and a worker pool.

**Job state.** A run is submitted over Kafka and executed by a worker in another process,
so the UI cannot hold the result in memory. It goes in a Redis hash, and the page reads it
from there.

**Pub/sub.** Progress ticks fan out to however many browsers have the page open. Kafka
carries the job; Redis pub/sub carries the "43 of 250 done" that the UI redraws on.

Everything degrades: if Redis is down the apps still run, just without caching or live
progress. A measurement tool that cannot run without its cache is a worse tool.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import suppress
from typing import Any

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

GEN_PREFIX = "gen:"  # generation cache
JOB_PREFIX = "job:"  # job state hash
PROGRESS_CHANNEL = "progress:{job_id}"
RESULT_TTL = 60 * 60 * 24 * 7
GEN_TTL = 60 * 60 * 24 * 30

_client: aioredis.Redis | None = None


# How long to wait for a cache that may not be there. With no timeout, every call to
# an absent Redis costs the operating system's full TCP connect timeout - 4 seconds on
# this machine - and a page that reads the cache three times took 12.5 of them to
# render. The cache is an optimisation; waiting four seconds to find out it is missing
# is slower than not having one.
CONNECT_TIMEOUT = float(os.environ.get("REDIS_CONNECT_TIMEOUT", "0.5"))
OP_TIMEOUT = float(os.environ.get("REDIS_OP_TIMEOUT", "2.0"))


def client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=CONNECT_TIMEOUT,
            socket_timeout=OP_TIMEOUT,
        )
    return _client


async def ping() -> bool:
    try:
        return bool(await client().ping())
    except Exception:
        return False


# --- generation cache ----------------------------------------------------------------


def gen_key(model: str, prompt: str, temperature: float, seed: int | None) -> str:
    digest = hashlib.sha256(
        json.dumps([model, prompt, temperature, seed], sort_keys=True).encode()
    ).hexdigest()
    return f"{GEN_PREFIX}{digest[:40]}"


async def get_generation(
    model: str, prompt: str, temperature: float, seed: int | None
) -> str | None:
    try:
        return await client().get(gen_key(model, prompt, temperature, seed))
    except Exception:
        return None  # a cold cache is slow, not broken


async def put_generation(
    model: str, prompt: str, temperature: float, seed: int | None, response: str
) -> None:
    with suppress(Exception):
        await client().set(gen_key(model, prompt, temperature, seed), response, ex=GEN_TTL)


async def cache_stats() -> dict[str, Any]:
    try:
        r = client()
        info = await r.info("stats")
        hits = int(info.get("keyspace_hits", 0))
        misses = int(info.get("keyspace_misses", 0))
        total = hits + misses
        return {
            "generations": len([k async for k in r.scan_iter(f"{GEN_PREFIX}*", count=500)]),
            "hit_rate": hits / total if total else 0.0,
            "hits": hits,
            "misses": misses,
        }
    except Exception:
        return {"generations": 0, "hit_rate": 0.0, "hits": 0, "misses": 0}


# --- job state -----------------------------------------------------------------------


async def create_job(job_id: str, app: str, params: dict) -> None:
    with suppress(Exception):
        await client().hset(
            f"{JOB_PREFIX}{job_id}",
            mapping={
                "app": app,
                "status": "queued",
                "params": json.dumps(params),
                "created": str(time.time()),
                "progress": "0",
                "total": str(params.get("limit", 0)),
            },
        )
        await client().expire(f"{JOB_PREFIX}{job_id}", RESULT_TTL)


async def update_job(job_id: str, **fields: Any) -> None:
    with suppress(Exception):
        await client().hset(
            f"{JOB_PREFIX}{job_id}",
            mapping={
                k: (json.dumps(v) if isinstance(v, dict | list) else str(v))
                for k, v in fields.items()
            },
        )


async def get_job(job_id: str) -> dict | None:
    try:
        data = await client().hgetall(f"{JOB_PREFIX}{job_id}")
        if not data:
            return None
        for key in ("params", "result"):
            # A field written before it was JSON, or written as a plain string, stays
            # a string rather than failing the whole lookup.
            if key in data:
                with suppress(json.JSONDecodeError, TypeError):
                    data[key] = json.loads(data[key])
        return data
    except Exception:
        return None


async def recent_jobs(app: str, limit: int = 12) -> list[dict]:
    """Most recent runs for one app, newest first."""
    out = []
    try:
        r = client()
        async for key in r.scan_iter(f"{JOB_PREFIX}*", count=500):
            data = await r.hgetall(key)
            if data.get("app") == app:
                data["job_id"] = key.removeprefix(JOB_PREFIX)
                out.append(data)
    except Exception:
        return []
    out.sort(key=lambda d: float(d.get("created", 0)), reverse=True)
    return out[:limit]


# --- live progress -------------------------------------------------------------------


async def publish_progress(job_id: str, payload: dict) -> None:
    with suppress(Exception):
        await client().publish(PROGRESS_CHANNEL.format(job_id=job_id), json.dumps(payload))


async def subscribe_progress(job_id: str):
    """Yield progress payloads until the job reports itself finished."""
    pubsub = client().pubsub()
    await pubsub.subscribe(PROGRESS_CHANNEL.format(job_id=job_id))
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        await pubsub.unsubscribe(PROGRESS_CHANNEL.format(job_id=job_id))
        await pubsub.aclose()
