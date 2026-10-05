"""The HTTP surface every product shares.

FastAPI is an optional extra. Importing this module without it raises something
that says so, rather than an AttributeError three frames deep.

The route table is deliberately small, because there are only four things a
person does with an agent product: start work, watch it, approve what it paused
on, and read the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import graphs, topics
from .web import html as console_html


class FastAPINotInstalledError(ImportError):
    pass


PENDING = "pending"
RUNNING = "running"
AWAITING_APPROVAL = "awaiting_approval"
DONE = "done"
FAILED = "failed"


@dataclass
class Runtime:
    """Everything a product's HTTP surface and worker need, injected.

    Injected rather than imported so the whole thing runs in a test against the
    in-memory bus and store, with no broker, no database and no model.
    """

    domain: str
    bus: object
    store: object
    graph: graphs.Graph
    group: str = "llm-workers"

    @property
    def topics(self) -> topics.Topics:
        return topics.Topics(self.domain)

    # ---------------------------------------------------------------- write

    def submit(self, run_id: str, entity: str, payload: dict) -> str:
        """Accept work. Publishes and returns; it does not run the graph.

        This is the whole argument for the bus: the request returns in
        milliseconds while one GPU serves the queue at its own pace.
        """
        key = topics.partition_key(self.domain, entity)
        self.store.put(
            "runs",
            run_id,
            {"run_id": run_id, "entity": entity, "status": PENDING, "visited": []},
        )
        self.bus.publish(self.topics.tasks, key, {"run_id": run_id, "payload": payload})
        return run_id

    def approve(self, run_id: str) -> dict:
        row = self.store.get("runs", run_id)
        if row is None:
            raise KeyError(run_id)
        if row["status"] != AWAITING_APPROVAL:
            raise ValueError(f"run {run_id} is {row['status']}, not awaiting approval")
        checkpoint = self._checkpoints[run_id]
        resumed = dict(checkpoint.state)
        resumed[graphs.APPROVED] = True
        return self._execute(
            run_id,
            checkpoint=graphs.Checkpoint(run_id, checkpoint.next_node, resumed),
        )

    def reject(self, run_id: str, reason: str = "") -> dict:
        row = self.store.get("runs", run_id)
        if row is None:
            raise KeyError(run_id)
        row.update({"status": FAILED, "reason": reason or "rejected by a person"})
        self.store.put("runs", run_id, row)
        self.bus.publish(self.topics.events, run_id, {"run_id": run_id, "event": "rejected"})
        return row

    # ---------------------------------------------------------------- worker

    _checkpoints: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._checkpoints = {}

    def drain(self, limit: int = 10) -> int:
        """Run one worker pass. Returns how many messages were handled."""
        handled = 0
        for message in self.bus.poll(self.topics.tasks, self.group, limit=limit):
            self._execute(message.value["run_id"], state=message.value.get("payload", {}))
            handled += 1
        return handled

    def _execute(self, run_id: str, *, state=None, checkpoint=None) -> dict:
        row = self.store.get("runs", run_id) or {"run_id": run_id, "visited": []}
        row["status"] = RUNNING
        self.store.put("runs", run_id, row)
        try:
            result = graphs.run(self.graph, state, run_id=run_id, checkpoint=checkpoint)
        except graphs.GraphInterruptedError as paused:
            self._checkpoints[run_id] = paused.checkpoint
            # The generations that produced the thing being approved are
            # recorded now, not when it resumes. A paused run has already cost
            # something and its row must say so.
            row.update(
                {
                    "status": AWAITING_APPROVAL,
                    "awaiting": paused.checkpoint.awaiting,
                    "visited": row.get("visited", []) + paused.partial.visited,
                    "llm_calls": row.get("llm_calls", 0) + paused.partial.llm_calls,
                }
            )
            self.store.put("runs", run_id, row)
            self.bus.publish(
                self.topics.approvals,
                run_id,
                {"run_id": run_id, "node": paused.checkpoint.awaiting},
            )
            return row
        except Exception as exc:  # noqa: BLE001 — a failed run goes to the dlq, not the floor
            row.update({"status": FAILED, "reason": f"{type(exc).__name__}: {exc}"})
            self.store.put("runs", run_id, row)
            self.bus.publish(self.topics.dlq, run_id, {"run_id": run_id, "error": str(exc)})
            return row

        row.update(
            {
                "status": DONE,
                "visited": row.get("visited", []) + result.visited,
                "llm_calls": row.get("llm_calls", 0) + result.llm_calls,
                "result": {k: v for k, v in result.state.items() if not k.startswith("_")},
            }
        )
        self.store.put("runs", run_id, row)
        self.bus.publish(self.topics.events, run_id, {"run_id": run_id, "event": "completed"})
        return row

    # ---------------------------------------------------------------- read

    def run_row(self, run_id: str) -> dict | None:
        return self.store.get("runs", run_id)

    def awaiting(self) -> list[dict]:
        return [r for r in self.store.rows("runs") if r.get("status") == AWAITING_APPROVAL]

    def runs(self) -> list[dict]:
        return self.store.rows("runs")

    def recent_events(self, limit: int = 20) -> list[dict]:
        """The event feed, peeked rather than consumed.

        Reading the console must not steal messages from the projector that is
        also consuming this topic.
        """
        out = []
        for topic in (self.topics.events, self.topics.approvals, self.topics.dlq):
            for message in self.bus.tail(topic, limit):
                out.append(
                    {
                        "topic": message.topic,
                        "key": message.key,
                        "partition": message.partition,
                        "offset": message.offset,
                        "event": message.value.get("event")
                        or message.value.get("node")
                        or message.value.get("error", ""),
                    }
                )
        return out[-limit:]


def create_app(runtime: Runtime):
    """The FastAPI application for one product."""
    try:
        from fastapi import FastAPI, HTTPException  # noqa: PLC0415 — optional extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise FastAPINotInstalledError(
            "fastapi is not installed; the Runtime works without it. "
            "Install with: uv add fastapi uvicorn"
        ) from exc

    from fastapi.responses import HTMLResponse  # noqa: PLC0415 — optional extra

    app = FastAPI(title=runtime.domain)

    @app.get("/", response_class=HTMLResponse)
    def console() -> str:
        """The operator console. One page, no build step, no npm."""
        return console_html(runtime.domain)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "domain": runtime.domain,
            "topics": list(runtime.topics.all()),
            "lag": runtime.bus.lag(runtime.topics.tasks, runtime.group),
        }

    @app.post("/intake", status_code=202)
    def intake(body: dict) -> dict:
        run_id = body.get("run_id") or f"run_{len(runtime.store.rows('runs')) + 1}"
        entity = body.get("entity")
        if not entity:
            raise HTTPException(status_code=422, detail="entity is required")
        runtime.submit(run_id, entity, body.get("payload", {}))
        return {"run_id": run_id, "status": PENDING}

    @app.get("/runs/{run_id}")
    def read_run(run_id: str) -> dict:
        row = runtime.run_row(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such run")
        return row

    @app.get("/runs")
    def list_runs() -> list[dict]:
        return runtime.runs()

    @app.get("/events")
    def events(limit: int = 20) -> list[dict]:
        return runtime.recent_events(limit)

    @app.post("/drain")
    def drain(limit: int = 10) -> dict:
        """Run one worker pass.

        Exposed so the console can demonstrate the queue without a supervisor
        process. In a deployment this is a loop in a worker, not a route.
        """
        return {"handled": runtime.drain(limit)}

    @app.get("/approvals")
    def approvals() -> list[dict]:
        return runtime.awaiting()

    @app.post("/approvals/{run_id}/approve")
    def approve(run_id: str) -> dict:
        try:
            return runtime.approve(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such run") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/approvals/{run_id}/reject")
    def reject(run_id: str, body: dict | None = None) -> dict:
        try:
            return runtime.reject(run_id, (body or {}).get("reason", ""))
        except KeyError:
            raise HTTPException(status_code=404, detail="no such run") from None

    return app
