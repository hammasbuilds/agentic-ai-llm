# observability

A run console for the platform: what ran, how long it took, **which way it travelled**,
and what failed.

`http.server`, one HTML file, a JSON Lines log. No Prometheus, no Grafana, no extra
dependency — the apps already pull in FastAPI and the rest, and a console is not a reason
to add a metrics stack on top.

```bash
# 1. run an app with recording on. Off unless this names a file.
AAL_TELEMETRY=runs.jsonl python scripts/run_app.py 01_localizer

# 2. in another terminal, read what it wrote
python observability/serve.py runs.jsonl
```

## This is not the job store

`apps/_platform/cache.py` holds live job state in Redis under a TTL, or in a dict when
Redis is absent. That is right for a page polling its own run — and it is gone on restart
and gone when the key expires. This file is the durable record of what ran.

Off unless `AAL_TELEMETRY` names a file. Every `runtime()` here already falls back to an
in-memory bus and store; an install that quietly started writing to disk would be the one
component that did not keep that promise.

## What is in the file

One JSON object per finished job:

```json
{"at": 1760000000.12, "app": "01_localizer", "outcome": "done", "seconds": 12.84,
 "transport": "inline", "items": 51}
```

**Not in the file: the parameters, the result, or the text of an error.** A measurement's
parameters can hold a pasted issue report, and an exception message can hold a path. The
error's *type* is recorded, because what a console needs at 3am is which failure keeps
happening. `tests/test_telemetry.py` puts a distinctive parameter through a job and
asserts it is absent from the log afterwards.

Both paths record: `_run_inline` in `apps/_platform/base.py` with `transport: inline`, and
`handle` in `worker.py` with `transport: kafka`. Instrumenting only the first would have
made every job that went over the bus invisible — and since nothing binds Kafka today, the
gap would have looked exactly like the truth until somebody started the worker.

## What the console shows

| panel | why it is there |
|---|---|
| **Which way it travelled** | Kafka, Redis, Postgres and Ollama adapters all ship and **no product binds one**. `inline: 100%` is a statement of fact, not a fault to fix — and the panel says so, so nobody goes looking for a broken broker |
| At a glance | runs, failures, p50/p95/longest, and total compute summed across runs |
| By app | runs, failures, items processed, p50/p95 and total time per app |
| What failed | by exception type |
| Recent runs | the tail, with transport and item count |

A percentile over fewer than twenty runs is marked as the handful it is, on the page and
in the per-app table.

## What it does not do

- It does not write to the log. It reads.
- It does not start an app or the worker.
- It binds `127.0.0.1` only, and that is not configurable.
- It computes nothing in the page. Every number comes from `collect.py`, pure functions
  over the events, tested without a server.
