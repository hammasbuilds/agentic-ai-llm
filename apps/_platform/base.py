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

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
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

    async def health() -> dict:
        redis_ok = await cache.ping()
        stats = await cache.cache_stats() if redis_ok else {}
        return {
            "redis": redis_ok,
            "kafka": await bus.available(),
            "model": await _model_up(model),
            "model_name": model.split(":")[0],
            "cached": stats.get("generations", 0),
        }

    def ctx(request: Request, **extra) -> dict:
        return {"request": request, "theme": theme, "icon": icon, **extra}

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
            if job and job.get("status") == "done":
                yield {"event": "done", "data": json.dumps({"job_id": job_id})}
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
        """The rendered result fragment; HTMX swaps this in when the stream ends."""
        job = await cache.get_job(job_id)
        if job is None or job.get("status") != "done":
            return HTMLResponse('<p class="muted">Still running…</p>')
        return tpl.TemplateResponse(
            request,
            result_template,
            ctx(request, job=job, result=job.get("result", {}), job_id=job_id),
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
