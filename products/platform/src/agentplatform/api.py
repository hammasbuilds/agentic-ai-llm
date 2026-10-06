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


@dataclass(frozen=True)
class DrainPass:
    """What one worker pass did, rather than how many messages it took.

    `handled` is kept, as the sum, because a caller asking "did the pass move
    anything" is asking a fair question - but it is derived from the three outcomes
    rather than counted independently, so it cannot disagree with them.
    """

    done: int = 0
    failed: int = 0
    awaiting_approval: int = 0

    @property
    def handled(self) -> int:
        return self.done + self.failed + self.awaiting_approval

    def __int__(self) -> int:
        return self.handled

    def __eq__(self, other: object) -> bool:
        """Compares equal to its own total, so `drain() == 1` still reads naturally."""
        if isinstance(other, int):
            return self.handled == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.done, self.failed, self.awaiting_approval))

    def as_dict(self) -> dict:
        return {
            "handled": self.handled,
            "done": self.done,
            "failed": self.failed,
            "awaiting_approval": self.awaiting_approval,
        }


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
        checkpoint = self._load_checkpoint(run_id)
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

    #: The table pauses live in. A plain in-process dict used to hold them, so a run
    #: could be approved only from the Python object that drained it - the web process
    #: saw `awaiting_approval` in the store, listed it under `/approvals`, and answered
    #: approve with 404. The store is shared; the dict was not.
    CHECKPOINTS = "checkpoints"

    def _save_checkpoint(self, checkpoint: graphs.Checkpoint) -> None:
        self.store.put(self.CHECKPOINTS, checkpoint.run_id, checkpoint.to_row())

    def checkpoint(self, run_id: str) -> graphs.Checkpoint:
        """The pause this run is sitting at, read from the store.

        Public because all twenty products needed it and all twenty reached into
        `rt._checkpoints["r1"].state` to get it - which is how a private in-process
        dict came to be load-bearing across the whole portfolio.
        """
        return self._load_checkpoint(run_id)

    def _load_checkpoint(self, run_id: str) -> graphs.Checkpoint:
        row = self.store.get(self.CHECKPOINTS, run_id)
        if row is None:
            raise KeyError(
                f"run {run_id} has no stored checkpoint; it was paused by a process "
                "that did not save one"
            )
        return graphs.Checkpoint.from_row(row)

    def drain(self, limit: int = 10) -> DrainPass:
        """Run one worker pass, and say what happened in it.

        It used to return a bare count of messages taken off the topic, which is a
        number that cannot go down: a pass where every run failed and went to the
        dead-letter queue reported the same `handled: 10` as a pass where every run
        completed. The console printed it as progress.

        The batch is acknowledged at the end rather than by `poll`, so a crash
        part-way through leaves the rest of it redeliverable.
        """
        done = failed = awaiting = 0
        for message in self.bus.poll(self.topics.tasks, self.group, limit=limit):
            row = self._execute(message.value["run_id"], state=message.value.get("payload", {}))
            status = row.get("status")
            if status == DONE:
                done += 1
            elif status == AWAITING_APPROVAL:
                awaiting += 1
            else:
                failed += 1
        if done or failed or awaiting:
            self.bus.commit(self.topics.tasks, self.group)
        return DrainPass(done=done, failed=failed, awaiting_approval=awaiting)

    def _execute(self, run_id: str, *, state=None, checkpoint=None) -> dict:
        row = self.store.get("runs", run_id) or {"run_id": run_id, "visited": []}
        row["status"] = RUNNING
        self.store.put("runs", run_id, row)
        try:
            result = graphs.run(self.graph, state, run_id=run_id, checkpoint=checkpoint)
        except graphs.GraphInterruptedError as paused:
            self._save_checkpoint(paused.checkpoint)
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
        return runtime.drain(limit).as_dict()

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
