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

Everything degrades: if Redis is down the apps still run, just without caching across
processes. A measurement tool that cannot run without its cache is a worse tool.

Degrading is not the same as discarding. Job state and progress have an in-process
fallback below, because without it an absent Redis did not slow the apps down - it
threw their answers away. `create_job` was a silent no-op, so `/run` redirected to a
job page that 404ed, while the measurement ran to completion in the background and
reported its result through the same suppressed write. The page said "No such job"
and nothing was logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

GEN_PREFIX = "gen:"  # generation cache
GEN_HITS = "stat:gen:hits"  # lookups this cache answered
GEN_MISSES = "stat:gen:misses"  # lookups it did not
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

# Shortening the timeout fixed the cost of one call. This fixes the number of them.
# Rendering a job page reads state, reads history and publishes a tick, and submitting
# a run writes twice - so on a machine with no Redis the page still paid the connect
# timeout several times over, serially. Once a connection has just failed, the next
# calls take the fallback immediately and one attempt per interval goes back to check.
DOWN_FOR = float(os.environ.get("REDIS_RETRY_AFTER", "5.0"))
_down_until = 0.0


class Unavailable(Exception):
    """Redis was found missing a moment ago; this call did not wait to find out again."""


async def call(op, *args: Any, **kwargs: Any) -> Any:
    """One Redis operation, with a short memory of having just failed."""
    global _down_until
    if time.monotonic() < _down_until:
        raise Unavailable(REDIS_URL)
    try:
        result = await op(*args, **kwargs)
    except Exception:
        _down_until = time.monotonic() + DOWN_FOR
        raise
    _down_until = 0.0  # it answered, so stop short-circuiting
    return result


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
        return bool(await call(client().ping))
    except Exception:
        return False


# --- generation cache ----------------------------------------------------------------


def gen_key(model: str, prompt: str, temperature: float, seed: int | None, num_predict: int) -> str:
    """Every input that changes the answer, and nothing else.

    `num_predict` was missing. It is passed to ollama as an option and caps the
    generation, so two calls differing only in it get different answers - and shared
    one key. `localize_eval` asks for 256 tokens on the locate prompt and 128 on the
    rerank through this same cache, so a prompt asked at one limit could be served the
    answer generated at the other: a reply truncated where the caller allowed more, or
    longer than the caller asked for, with nothing to indicate either.

    Adding it changes every digest, so the existing entries are missed once rather
    than returned wrongly. That is the right direction for a key that was too narrow.
    """
    digest = hashlib.sha256(
        json.dumps([model, prompt, temperature, seed, num_predict], sort_keys=True).encode()
    ).hexdigest()
    return f"{GEN_PREFIX}{digest[:40]}"


async def get_generation(
    model: str, prompt: str, temperature: float, seed: int | None, num_predict: int
) -> str | None:
    try:
        found = await call(client().get, gen_key(model, prompt, temperature, seed, num_predict))
    except Exception:
        return None  # a cold cache is slow, not broken
    # Counted here, on this cache's own keys. `cache_stats` used to divide Redis'
    # `keyspace_hits` by `keyspace_misses`, which are server-wide across every key and
    # every database on the instance: job-state reads, the `scan_iter` in this same
    # module, and anything else sharing the Redis. It was reported as the generation
    # cache's hit rate and had no relation to it. A failed INCR is not worth failing a
    # lookup over, so it is suppressed - and `cache_stats` says when that has happened.
    with suppress(Exception):
        await call(client().incr, GEN_HITS if found is not None else GEN_MISSES)
    return found


async def put_generation(
    model: str,
    prompt: str,
    temperature: float,
    seed: int | None,
    response: str,
    num_predict: int,
) -> None:
    with suppress(Exception):
        await call(
            client().set,
            gen_key(model, prompt, temperature, seed, num_predict),
            response,
            ex=GEN_TTL,
        )


#: What `cache_stats` returns when Redis cannot be read. `hit_rate` is None rather than
#: 0.0: a cache nobody asked anything of has no hit rate, and reporting one as zero is
#: the same claim as a cache that missed every time.
_NO_STATS: dict[str, Any] = {
    "generations": 0,
    "hit_rate": None,
    "hits": 0,
    "misses": 0,
    "lookups": 0,
}


async def cache_stats() -> dict[str, Any]:
    """The generation cache's own figures, over its own keys.

    `hits + misses` is the denominator and is returned as `lookups`, because a 100% hit
    rate over four lookups and over four hundred thousand are different claims and read
    identically without it.
    """
    try:
        r = client()
        hits = int(await call(r.get, GEN_HITS) or 0)
        misses = int(await call(r.get, GEN_MISSES) or 0)
        lookups = hits + misses
        return {
            "generations": len([k async for k in r.scan_iter(f"{GEN_PREFIX}*", count=500)]),
            "hit_rate": hits / lookups if lookups else None,
            "hits": hits,
            "misses": misses,
            "lookups": lookups,
        }
    except Exception:
        return dict(_NO_STATS)


# --- the fallback for when Redis is not there -----------------------------------------
#
# Redis holds job state because a worker in another process runs the job. But a worker
# in another process only exists when Kafka is up to carry the job to it, and the same
# `docker compose up` brings up both - so on a machine with no Redis there is no worker
# either, and `base._run_inline` runs the job in this process. An in-process dict is
# therefore not a degraded substitute for the cross-process store: in that exact
# configuration it is the whole population.
#
# Bounded, because a long-lived process would otherwise accumulate every job it ever
# ran. Oldest-first eviction, which for job state is also least-interesting-first.
# These do not survive a restart, which is the honest limit of the fallback and is why
# Redis is still the thing to run.

_LOCAL_JOBS: dict[str, dict[str, str]] = {}
_LOCAL_MAX = 256
_LOCAL_WAITERS: dict[str, set[asyncio.Queue]] = {}
_TERMINAL = ("done", "error")
_POLL = 0.25  # how often a local subscriber re-checks for a result it may have missed


def _remember(job_id: str, fields: dict[str, str]) -> None:
    job = _LOCAL_JOBS.setdefault(job_id, {})
    job.update(fields)
    while len(_LOCAL_JOBS) > _LOCAL_MAX:
        _LOCAL_JOBS.pop(next(iter(_LOCAL_JOBS)))


def _encode(fields: dict[str, Any]) -> dict[str, str]:
    return {k: (json.dumps(v) if isinstance(v, dict | list) else str(v)) for k, v in fields.items()}


def _decode(data: dict[str, str]) -> dict:
    data = dict(data)
    for key in ("params", "result"):
        # A field written before it was JSON, or written as a plain string, stays a
        # string rather than failing the whole lookup.
        if key in data:
            with suppress(json.JSONDecodeError, TypeError):
                data[key] = json.loads(data[key])
    return data


# --- job state -----------------------------------------------------------------------


async def create_job(job_id: str, app: str, params: dict) -> None:
    fields = {
        "app": app,
        "status": "queued",
        "params": json.dumps(params),
        "created": str(time.time()),
        "progress": "0",
        "total": str(params.get("limit", 0)),
    }
    try:
        await call(client().hset, f"{JOB_PREFIX}{job_id}", mapping=fields)
        await call(client().expire, f"{JOB_PREFIX}{job_id}", RESULT_TTL)
    except Exception:
        # Not suppressed: a job nobody recorded is a job whose result has nowhere to go.
        _remember(job_id, fields)


async def update_job(job_id: str, **fields: Any) -> None:
    encoded = _encode(fields)
    try:
        await call(client().hset, f"{JOB_PREFIX}{job_id}", mapping=encoded)
    except Exception:
        _remember(job_id, encoded)


async def get_job(job_id: str) -> dict | None:
    data: dict[str, str] = {}
    with suppress(Exception):
        data = await call(client().hgetall, f"{JOB_PREFIX}{job_id}") or {}
    # Local fields win where both have one: Redis can go down mid-run, leaving a job
    # created there and finished here, and the later writes are the ones worth reading.
    local = _LOCAL_JOBS.get(job_id)
    if local:
        data = {**data, **local}
    return _decode(data) if data else None


async def recent_jobs(app: str, limit: int = 12) -> list[dict]:
    """Most recent runs for one app, newest first."""
    out = []
    seen = set()
    with suppress(Exception):
        r = client()
        await call(r.ping)  # one attempt, so a missing Redis costs one timeout not a scan
        async for key in r.scan_iter(f"{JOB_PREFIX}*", count=500):
            data = await r.hgetall(key)
            job_id = key.removeprefix(JOB_PREFIX)
            # Local fields win, as they do in `get_job`. They did not here: a job
            # created in Redis and finished locally after it went down was listed with
            # its Redis row alone, so the history page showed `queued` for a run the
            # job page showed as `done` - two pages in the same app disagreeing about
            # the same job, with the stale one winning on the page that lists them.
            local = _LOCAL_JOBS.get(job_id)
            if local:
                data = {**data, **local}
            if data.get("app") == app:
                data["job_id"] = job_id
                seen.add(job_id)
                out.append(data)
    for job_id, data in _LOCAL_JOBS.items():
        if data.get("app") == app and job_id not in seen:
            out.append({**data, "job_id": job_id})
    out.sort(key=lambda d: float(d.get("created", 0)), reverse=True)
    return out[:limit]


# --- live progress -------------------------------------------------------------------


async def publish_progress(job_id: str, payload: dict) -> None:
    try:
        await call(client().publish, PROGRESS_CHANNEL.format(job_id=job_id), json.dumps(payload))
    except Exception:
        for queue in _LOCAL_WAITERS.get(job_id, ()):
            queue.put_nowait(payload)


async def _local_progress(job_id: str) -> AsyncIterator[dict]:
    """The same stream, carried by a queue instead of by Redis.

    The subscriber arrives after the job was submitted - the browser has to load the
    page first - so a short run can finish before anyone is listening, and a worker
    that died never sends anything at all. Waiting on the queue alone would hang the
    page on a job that is already complete, which is the failure this whole fallback
    exists to remove, so each wait is bounded and the job's own status is the authority
    on whether it is over.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _LOCAL_WAITERS.setdefault(job_id, set()).add(queue)
    try:
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=_POLL)
                continue
            except TimeoutError:
                pass
            status = (_LOCAL_JOBS.get(job_id) or {}).get("status")
            if status in _TERMINAL:
                yield {"status": status, "note": (_LOCAL_JOBS[job_id].get("error") or "")}
                return
    finally:
        waiters = _LOCAL_WAITERS.get(job_id)
        if waiters:
            waiters.discard(queue)
            if not waiters:
                _LOCAL_WAITERS.pop(job_id, None)


async def subscribe_progress(job_id: str) -> AsyncIterator[dict]:
    """Yield progress payloads until the job reports itself finished."""
    try:
        pubsub = client().pubsub()
        await call(pubsub.subscribe, PROGRESS_CHANNEL.format(job_id=job_id))
    except Exception:
        # No Redis: the job is running in this process, so its progress is here too.
        async for payload in _local_progress(job_id):
            yield payload
        return
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(PROGRESS_CHANNEL.format(job_id=job_id))
        with suppress(Exception):
            await pubsub.aclose()
