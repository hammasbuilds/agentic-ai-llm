"""One FastAPI factory, ten apps.

Each app supplies three things: a theme slug, a form definition, and an async `runner`
that does the measurement. Everything else - job submission over Kafka, state in Redis,
live progress over SSE, the history page, health checks - is identical and lives here.

The shape that matters is that **the web process never runs a measurement**. A submit
publishes to Kafka and returns a job id immediately; a worker picks it up and streams
ticks back. If Kafka is not reachable the job runs in a background task instead and the
UI says so, because a demo that only works with the full stack up is a demo nobody runs.
"""

from __future__ import annotations

from datetime import datetime

import time

import os

import asyncio
import html
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from sse_starlette.sse import EventSourceResponse

from . import bus, cache
from . import model as model_client
from .themes import get as get_theme

HERE = Path(__file__).resolve().parent


@dataclass
class Field:
    """One form control."""

    name: str
    label: str
    kind: str = "number"  # number | text | select | textarea
    default: Any = ""
    hint: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)
    min: int | None = None
    max: int | None = None


# A runner reports progress through this callback and returns the final result dict.
Emit = Callable[[int, int, str], Awaitable[None]]
Runner = Callable[[dict, Emit], Awaitable[dict]]


async def _model_up(name: str) -> bool:
    """Whether the model the apps generate with is there.

    Asked of `model`, which is the module that does the generating. This had its own
    `OLLAMA = os.environ.get("OLLAMA_URL", ...)` and its own copy of the same request -
    two constants for one setting, so pointing the client somewhere else left the health
    badge talking to the old server. The badge and the generator have to agree about
    which Ollama they mean, and the only way to guarantee that is one of them asking the
    other.
    """
    return await model_client.available(name)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Close the shared Kafka producer on shutdown; on_event is deprecated."""
    yield
    await bus.close()


def _as_epoch(value: object) -> float | None:
    """A float, or None for anything that is not a usable timestamp.

    Job fields arrive from Redis as strings, and a hash written halfway is a state this
    platform already handles elsewhere, so a bad value here renders as a dash rather than
    raising out of a template on the index page.
    """
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # Zero is the default `cache.recent_jobs` substitutes for a missing key, not a time.
    return seconds if seconds > 0 else None


def format_when(value: object) -> str:
    """An absolute local time, as short as the distance from now allows.

    The column heading says "When" and the cell used to say `1760012345`.
    """
    seconds = _as_epoch(value)
    if seconds is None:
        return "—"
    moment = datetime.fromtimestamp(seconds)
    now = datetime.now()
    if moment.date() == now.date():
        return moment.strftime("%H:%M")
    if (now - moment).days < 7:
        return moment.strftime("%a %H:%M")
    if moment.year == now.year:
        return moment.strftime("%-d %b %H:%M") if os.name != "nt" else moment.strftime("%d %b %H:%M")
    return moment.strftime("%d %b %Y")


def format_stamp(value: object) -> str:
    """The full local timestamp, for the `title` on a shortened cell."""
    seconds = _as_epoch(value)
    if seconds is None:
        return "no timestamp recorded"
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


def format_ago(value: object) -> str:
    """How long ago, in the largest unit that still says something."""
    seconds = _as_epoch(value)
    if seconds is None:
        return "—"
    gap = max(0.0, time.time() - seconds)
    if gap < 45:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    return f"{int(gap // 86400)} d ago"


def create_app(
    *,
    slug: str,
    icon: str,
    runner: Runner,
    fields: list[Field],
    result_template: str,
    about: str,
    templates_dir: Path,
    model: str = "qwen2.5-coder:14b",
) -> FastAPI:
    theme = get_theme(slug)
    app = FastAPI(title=theme.name, docs_url="/api/docs", lifespan=_lifespan)
    # The form and the runner, reachable from the app object. Nothing could get at
    # either from outside `create_app`, which is why no test had ever called a
    # runner: the only way in was to POST a form and wait for a real measurement.
    app.state.fields = fields
    app.state.runner = runner
    app.state.slug = slug

    # App templates first so a per-app `result.html` wins, then the shared shell.
    tpl = Jinja2Templates(directory=[str(templates_dir), str(HERE / "templates")])
    # A field the result does not carry is an error, not an empty string.
    #
    # Jinja's default renders `{{ result.beats_baseline }}` as "" when the key is
    # gone, which is exactly what app 03 shipped: the runner split that field into
    # `vs_always_safe` and `vs_majority`, the template kept four references to the old
    # name, and every run of it rendered a page with holes and returned 200.
    # `StrictUndefined` raises, and `job_result` turns that into the fragment that
    # names the keys the result does have - so the same mistake is visible on the page
    # instead of being a blank where a number should be.
    tpl.env.undefined = StrictUndefined

    # A "When" column was printing `1760012345`, on the one list whose whole purpose is
    # to say whether a run is from this afternoon. Registered on the shared environment,
    # so both tables and any later one get them.
    tpl.env.filters["when"] = format_when
    tpl.env.filters["stamp"] = format_stamp
    tpl.env.filters["ago"] = format_ago
    # Reachable from the app object, for the same reason `fields` and `runner` are:
    # a setting nothing can read from outside this function is a setting no test can
    # assert, and this one is the difference between a missing field raising and
    # rendering as a blank.
    app.state.templates = tpl

    async def health() -> dict:
        redis_ok = await cache.ping()
        stats = await cache.cache_stats() if redis_ok else {}
        return {
            "redis": redis_ok,
            "kafka": await bus.available(),
            "model": await _model_up(model),
            "model_name": model.split(":")[0],
            "cached": stats.get("generations", 0),
            # The hit rate and its denominator. These were computed in `cache_stats`
            # and read by nothing, which is how they went unnoticed as the server-wide
            # `keyspace_hits` rather than this cache's own. `None` means nobody has
            # looked anything up yet, which is not the same as having missed.
            "cache_hit_rate": stats.get("hit_rate"),
            "cache_lookups": stats.get("lookups", 0),
        }

    def ctx(request: Request, **extra) -> dict:
        # `nav_path` so the masthead can mark the page you are on. Three identical links
        # on all three pages said nothing about which one you were looking at. The path
        # comes from the request rather than from a flag each route passes, so a page
        # added later is marked without anyone remembering to.
        return {
            "request": request,
            "theme": theme,
            "icon": icon,
            "nav_path": request.url.path,
            **extra,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return tpl.TemplateResponse(
            request,
            "index.html",
            ctx(
                request,
                health=await health(),
                fields=fields,
                recent=await cache.recent_jobs(slug, 5),
            ),
        )

    @app.post("/run")
    async def run(request: Request, background: BackgroundTasks):
        form = await request.form()
        params = {f.name: _coerce(form.get(f.name, f.default), f) for f in fields}

        job_id, via_kafka = await bus.submit(slug, params)
        await cache.create_job(job_id, slug, params)

        if not via_kafka:
            # No bus: run it here so the app is still usable, and record that the
            # result did not go through the log.
            background.add_task(_run_inline, slug, job_id, params, runner)
            await cache.update_job(job_id, transport="inline")
        else:
            await cache.update_job(job_id, transport="kafka")

        return RedirectResponse(f"/job/{job_id}", status_code=303)

    @app.get("/job/{job_id}", response_class=HTMLResponse)
    async def job_page(request: Request, job_id: str):
        job = await cache.get_job(job_id)
        if job is None:
            return HTMLResponse("<h1>No such job</h1>", status_code=404)
        return tpl.TemplateResponse(
            request,
            "job.html",
            ctx(
                request,
                health=await health(),
                job=job,
                job_id=job_id,
                result_template=result_template,
            ),
        )

    @app.get("/job/{job_id}/stream")
    async def stream(job_id: str):
        """Server-sent events, fed by Redis pub/sub rather than by polling."""

        async def gen():
            job = await cache.get_job(job_id)
            # Any TERMINAL status, not just "done". The loop below already treats both
            # "done" and "error" as the end of the stream; this pre-check - for a job that
            # finished before the browser opened the stream - checked only "done". So a run
            # that failed fell through to `subscribe_progress` and waited for a message
            # that was never coming: the run was over, so nothing would ever publish
            # again. The connection stayed open and the progress bar never finished, on
            # the one outcome where the reader most needs to be told it is over.
            #
            # Found by a sweep that drove /stream on ten apps with no model running - so
            # every job ended in "error" - and blocked for forty minutes on three seconds
            # of CPU.
            if job and job.get("status") in ("done", "error"):
                yield {"event": "done", "data": json.dumps({"job_id": job_id, **job})}
                return
            try:
                async for payload in cache.subscribe_progress(job_id):
                    if payload.get("status") in ("done", "error"):
                        yield {"event": "done", "data": json.dumps(payload)}
                        return
                    yield {"event": "tick", "data": json.dumps(payload)}
            except asyncio.CancelledError:
                return

        return EventSourceResponse(gen())

    @app.get("/job/{job_id}/result", response_class=HTMLResponse)
    async def job_result(request: Request, job_id: str):
        """The rendered result fragment; job.html fetches this when the stream ends.

        A result whose shape the template does not expect used to raise out of Jinja
        and come back as a 500. The page then showed nothing at all and sat on
        "Still running…" for a job that had finished. Any of these produced it:

          * a result cached by an older version of the app, which is the ordinary case
            because job state outlives a deploy in Redis;
          * a run that finished with `{}` because its graph exited early;
          * a key renamed in the app and not in its template.

        The fragment below says which keys the result actually has, because the thing
        a reader needs is the difference between "it failed" and "it finished and this
        page cannot show it". The traceback still goes to the log; it is just not the
        only place the failure appears.
        """
        job = await cache.get_job(job_id)
        if job is None or job.get("status") != "done":
            return HTMLResponse('<p class="muted">Still running…</p>')
        result = job.get("result", {})
        try:
            return tpl.TemplateResponse(
                request,
                result_template,
                ctx(request, job=job, result=result, job_id=job_id),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "%s: cannot render the result of job %s", slug, job_id
            )
            names = sorted(map(str, result)) if isinstance(result, dict) else []
            keys = ", ".join(names) if names else "none"
            return HTMLResponse(
                '<p class="muted">This job finished, and this page cannot display its '
                f"result. Keys in it: {html.escape(keys)}. The reason is in the "
                "server log.</p>",
                status_code=200,
            )

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        jobs = await cache.recent_jobs(slug, 40)
        replayed = await bus.replay_completed(slug, 40)
        return tpl.TemplateResponse(
            request,
            "history.html",
            ctx(request, health=await health(), jobs=jobs, replayed=replayed),
        )

    @app.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request):
        return tpl.TemplateResponse(
            request, "about.html", ctx(request, health=await health(), about=about)
        )

    @app.get("/healthz")
    async def healthz():
        h = await health()
        return JSONResponse(h, status_code=200 if h["model"] else 503)

    return app


def _coerce(value: Any, f: Field) -> Any:
    if f.kind == "number":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return f.default
        if f.min is not None:
            n = max(f.min, n)
        if f.max is not None:
            n = min(f.max, n)
        return n
    return value


async def _run_inline(app_slug: str, job_id: str, params: dict, runner: Runner) -> None:
    """Fallback path when Kafka is down. Same runner, same events, no replay."""

    async def emit(done: int, total: int, note: str = "") -> None:
        await cache.update_job(job_id, progress=done, total=total)
        await cache.publish_progress(
            job_id, {"done": done, "total": total, "note": note, "status": "running"}
        )

    await cache.update_job(job_id, status="running")
    try:
        result = await runner(params, emit)
        await cache.update_job(job_id, status="done", result=result)
        await cache.publish_progress(job_id, {"status": "done"})
    except Exception as exc:  # a failed measurement must not look like a hung one
        await cache.update_job(job_id, status="error", error=str(exc)[:400])
        await cache.publish_progress(job_id, {"status": "error", "note": str(exc)[:200]})
