"""The worker: consumes `jobs.requested`, runs the measurement, streams the result back.

One process, one GPU, one job at a time. That is not a limitation to work around - it is
the actual constraint, and making it explicit is better than letting ten web processes
each start a run and discover the constraint by thrashing VRAM.

    python worker.py              # all apps
    python worker.py --apps localizer kill-rate

What it does per message:

1. mark the job running in Redis, so the page shows it moved off the queue
2. call the app's own `runner`, which streams progress through `emit`
3. publish each tick to Redis pub/sub (the browser's SSE feed) and to `jobs.progress`
4. write the result to Redis and publish a final record to `jobs.completed`

Step 4 is the one that matters after a crash. Redis keys expire; `jobs.completed` does not,
so an hour of GPU time survives a restart, a flushed cache or a schema change.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import signal
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from apps._platform import bus, cache  # noqa: E402

APPS_DIR = ROOT / "apps"


def load_runners() -> dict[str, object]:
    """Import every apps/NN_name/app.py and index its runner by theme slug.

    The directories are digit-prefixed so they sort in the order the README lists them,
    which is not an importable module name - hence loading by file path.
    """
    runners: dict[str, object] = {}
    for path in sorted(APPS_DIR.glob("[0-9][0-9]_*/app.py")):
        name = f"aal_{path.parent.name}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            print(f"  !! {path.parent.name} failed to import: {exc}")
            continue
        slug = getattr(module, "SLUG", None) or module.app.title.lower().replace(" ", "-")
        runners[slug] = module.runner
        print(f"  loaded {path.parent.name:22} -> {slug}")
    return runners


async def handle(job_id: str, app: str, params: dict, runner) -> None:
    async def emit(done: int, total: int, note: str = "") -> None:
        await cache.update_job(job_id, progress=done, total=total)
        await cache.publish_progress(
            job_id, {"done": done, "total": total, "note": note, "status": "running"}
        )
        await bus.emit_progress(job_id, app, done, total, note)

    await cache.update_job(job_id, status="running")
    try:
        result = await runner(params, emit)
        await cache.update_job(job_id, status="done", result=result)
        await cache.publish_progress(job_id, {"status": "done"})
        # The durable record. Everything above this line is recoverable from it.
        await bus.emit_completed(job_id, app, result)
        print(f"  done {job_id} ({app})")
    except Exception as exc:
        traceback.print_exc()
        await cache.update_job(job_id, status="error", error=str(exc)[:400])
        await cache.publish_progress(job_id, {"status": "error", "note": str(exc)[:200]})
        print(f"  FAILED {job_id} ({app}): {exc}")


async def consume_one(ev: object, runners: dict) -> None:
    """One message off `jobs.requested`. Never raises for a malformed one.

    Each outcome a message can have is named, because two of them were previously
    indistinguishable from nothing happening: a message for an app this worker does not
    serve was skipped with no log line at all, and one missing `job_id` killed the
    process rather than being reported.
    """
    if not isinstance(ev, dict):
        print(f"  !! ignored: a message that is not an object ({type(ev).__name__})")
        return
    job_id, app = ev.get("job_id"), ev.get("app")
    if not isinstance(job_id, str) or not job_id:
        print(f"  !! ignored: no job_id in {sorted(ev)[:6]}")
        return
    if not isinstance(app, str) or not app:
        print(f"  !! ignored: job {job_id} names no app")
        return
    runner = runners.get(app)
    if runner is None:
        # Logged, not silent. This branch's offset handling is also why `--apps` takes
        # a consumer group of its own.
        print(f"  -- not mine: {job_id} ({app}); this worker serves {sorted(runners)}")
        return
    print(f"  picked {job_id} ({app})")
    params = ev.get("params")
    await handle(job_id, app, params if isinstance(params, dict) else {}, runner)


async def main(argv: list[str] | None = None, stop: asyncio.Event | None = None) -> int:
    """Consume until stopped.

    `argv` and `stop` are injectable so the loop can be driven in a test. It had
    none, and all three defects an independent review found were in this loop - a
    test exercising only the helper it calls left every one of them passing.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", nargs="*", help="only consume jobs for these slugs")
    ap.add_argument("--group", default="workers")
    args = ap.parse_args(argv)

    print("loading apps...")
    runners = load_runners()
    if args.apps:
        runners = {k: v for k, v in runners.items() if k in set(args.apps)}
    if not runners:
        print("no runners loaded")
        return 1
    print(f"serving {len(runners)} apps: {', '.join(sorted(runners))}\n")

    if not await bus.available():
        print("Kafka is not reachable. Start it with:")
        print("  docker compose up -d")
        return 1

    # A filtered worker gets its own group. With `--apps`, a job for an app this
    # process does not serve was skipped by `continue` below - and the consumer
    # auto-commits, so the offset advanced and no worker in the group could ever see
    # that job again. It stayed `queued` in Redis for ever, which on the documented
    # single-worker deployment means the run the user submitted silently never happens.
    #
    # Deriving the group from the filter keeps those offsets out of the shared group's,
    # so an unfiltered worker started later still picks the job up.
    group = args.group
    if args.apps:
        group = f"{args.group}-{'+'.join(sorted(runners))}"
        print(
            f"  --apps given, so consuming as group {group!r} rather than "
            f"{args.group!r}: a filtered worker sharing the group commits past the "
            "jobs it declines, and then nothing serves them."
        )
    consumer = bus.consumer(bus.TOPIC_REQUESTED, group=group, from_beginning=False)
    await consumer.start()
    print(f"consuming {bus.TOPIC_REQUESTED} as group {group!r}. ctrl-c to stop.\n")

    stopping = stop if stop is not None else asyncio.Event()

    def _stop(*_):
        stopping.set()

    with contextlib_suppress():
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

    try:
        while not stopping.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=1)
            for records in batch.values():
                for rec in records:
                    # Every message inside a try. `ev['job_id']` was a direct index out
                    # here, outside `handle`'s except - so one message without that key
                    # raised KeyError straight out of `main()` and killed the only
                    # process that owns the GPU. The topic is created with
                    # `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"` and validates nothing,
                    # so anything at all can be published to it.
                    try:
                        await consume_one(rec.value, runners)
                    except Exception as exc:  # noqa: BLE001
                        traceback.print_exc()
                        print(f"  !! skipped a message: {type(exc).__name__}: {exc}")
    finally:
        await consumer.stop()
        await bus.close()
    return 0


class contextlib_suppress:
    """signal.signal raises on some Windows shells; not worth failing the worker for."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
