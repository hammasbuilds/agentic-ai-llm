import pytest

from agentplatform import api, graphs
from agentplatform.graphs import END, Graph, Node
from agentplatform.ports import InMemoryBus, InMemoryStore

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def graph(calls=None):
    calls = calls if calls is not None else []
    return Graph(
        nodes={
            "draft": Node(
                "draft", graphs.LLM, lambda s: calls.append("draft") or {"draft": "hi"}
            ),
            "approve": Node("approve", graphs.INTERRUPT),
            "send": Node("send", graphs.TOOL, lambda s: {"sent": True}),
        },
        entry="draft",
        edges={"draft": "approve", "approve": "send", "send": END},
    )


def runtime(calls=None):
    return api.Runtime(
        domain="crm", bus=InMemoryBus(), store=InMemoryStore(), graph=graph(calls)
    )


def test_health_names_the_topics_and_the_lag():
    client = TestClient(api.create_app(runtime()))
    body = client.get("/health").json()
    assert body["topics"][0] == "crm.intake"
    assert body["lag"] == 0


def test_intake_returns_immediately_without_running_the_graph():
    calls = []
    rt = runtime(calls)
    client = TestClient(api.create_app(rt))
    response = client.post("/intake", json={"entity": "4192", "payload": {"x": 1}})
    assert response.status_code == 202
    assert response.json()["status"] == api.PENDING
    assert calls == []  # the GPU has not been touched
    assert rt.bus.lag("crm.tasks", rt.group) == 1


def test_intake_without_an_entity_is_refused():
    client = TestClient(api.create_app(runtime()))
    assert client.post("/intake", json={}).status_code == 422


def test_the_worker_drains_the_queue_and_the_run_pauses_for_approval():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    assert rt.drain() == 1
    row = client.get("/runs/r1").json()
    assert row["status"] == api.AWAITING_APPROVAL
    assert row["awaiting"] == "approve"


def test_a_paused_run_already_reports_what_it_cost():
    # A run waiting for approval has already spent generations producing the
    # thing being approved. Reporting zero until it resumes makes the only
    # interesting cost invisible.
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    paused = client.get("/runs/r1").json()
    assert paused["llm_calls"] == 1
    assert paused["visited"] == ["draft", "approve"]

    done = client.post("/approvals/r1/approve").json()
    assert done["llm_calls"] == 1  # resuming added none
    # "approve" does not appear twice: resuming starts at the node *after* the
    # interrupt, so the pause itself is not re-entered either.
    assert done["visited"] == ["draft", "approve", "send"]


def test_the_approvals_queue_lists_what_is_waiting():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    assert [r["run_id"] for r in client.get("/approvals").json()] == ["r1"]


def test_approving_resumes_without_regenerating():
    calls = []
    rt = runtime(calls)
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    assert calls == ["draft"]
    body = client.post("/approvals/r1/approve").json()
    assert body["status"] == api.DONE
    assert body["result"]["sent"] is True
    assert calls == ["draft"]


def test_rejecting_ends_the_run_with_a_reason():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    body = client.post("/approvals/r1/reject", json={"reason": "wrong contact"}).json()
    assert body["status"] == api.FAILED
    assert body["reason"] == "wrong contact"


def test_approving_a_run_that_is_not_waiting_is_a_conflict():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    client.post("/approvals/r1/approve")
    assert client.post("/approvals/r1/approve").status_code == 409


def test_an_unknown_run_is_a_404():
    client = TestClient(api.create_app(runtime()))
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/approvals/nope/approve").status_code == 404


def test_a_failing_node_sends_the_run_to_the_dead_letter_queue():
    def boom(state):
        raise RuntimeError("tool exploded")

    rt = api.Runtime(
        domain="crm",
        bus=InMemoryBus(),
        store=InMemoryStore(),
        graph=Graph(
            nodes={"a": Node("a", graphs.TOOL, boom)},
            entry="a",
            edges={"a": END},
        ),
    )
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    assert client.get("/runs/r1").json()["status"] == api.FAILED
    assert len(rt.bus.poll("crm.dlq", "humans")) == 1


def test_completion_is_announced_on_the_events_topic():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})
    rt.drain()
    client.post("/approvals/r1/approve")
    events = rt.bus.poll("crm.events", "audit")
    assert [e.value["event"] for e in events] == ["completed"]


# -- a pass that moved nothing forward ------------------------------------


def _always_failing_runtime() -> api.Runtime:
    def boom(state):
        raise RuntimeError("tool exploded")

    return api.Runtime(
        domain="crm",
        bus=InMemoryBus(),
        store=InMemoryStore(),
        graph=Graph(nodes={"a": Node("a", graphs.TOOL, boom)}, entry="a", edges={"a": END}),
    )


def test_a_pass_where_every_run_failed_does_not_report_like_a_pass_that_worked():
    """`drain` returned a count of messages taken off the topic, and nothing else.

    Three runs into the dead-letter queue and three runs completed both answered
    `handled: 3`. The console drew that number as progress, so a worker whose every
    execution was failing looked identical to one doing the work.
    """
    rt = _always_failing_runtime()
    client = TestClient(api.create_app(rt))
    for i in range(3):
        client.post("/intake", json={"run_id": f"r{i}", "entity": "4192"})

    result = rt.drain()
    assert result.handled == 3
    assert (result.done, result.failed, result.awaiting_approval) == (0, 3, 0)
    assert len(rt.bus.poll("crm.dlq", "humans")) == 3
    assert result == 3  # the old reading still works, and is now the sum of three


def test_an_empty_pass_commits_nothing_and_says_nothing_happened():
    rt = _always_failing_runtime()
    result = rt.drain()
    assert (result.handled, result.done, result.failed, result.awaiting_approval) == (
        0,
        0,
        0,
        0,
    )


def test_a_batch_is_acknowledged_by_the_worker_rather_than_by_polling():
    """So a worker that dies part-way through a batch has not consumed it.

    `poll` used to move the committed offset itself, which left `commit` with no
    callers anywhere in the repository and made the dead-letter queue the only way a
    message could survive a crash - it was not.
    """
    rt = _always_failing_runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "4192"})

    assert rt.bus.lag("crm.tasks", rt.group) == 1
    rt.bus.poll("crm.tasks", rt.group, limit=10)  # polled, then the worker dies
    assert rt.bus.lag("crm.tasks", rt.group) == 1, "polling is not finishing"
    rt.bus.restart("crm.tasks", rt.group)

    assert rt.drain().handled == 1, "redelivered to the restarted worker"
    assert rt.bus.lag("crm.tasks", rt.group) == 0, "and acknowledged once it was handled"


# -- a pause that outlives the process that made it -----------------------


def test_a_second_runtime_sharing_the_bus_and_store_can_approve(tmp_path):
    """Approval was impossible from anywhere but the process that drained the run.

    `Runtime._checkpoints` was a plain in-process dict. A web process sharing the bus
    and the store with a worker saw the row as `awaiting_approval`, listed it under
    `/approvals`, and answered `POST /approvals/{id}/approve` with 404 "no such run" -
    while `products/README.md` sells the chain "HTTP in -> bus -> drained by a worker
    -> paused for approval -> resumed". It closed only when the worker and the web
    process were the same Python object, which `scripts/smoke_serve.py` guarantees by
    running uvicorn in a thread of the same process.
    """
    bus, store = InMemoryBus(), InMemoryStore()
    graph = Graph(
        nodes={
            "draft": Node("draft", graphs.RULES, lambda s: {"draft": "pay"}),
            "approve": Node("approve", graphs.INTERRUPT),
            "pay": Node("pay", graphs.TOOL, lambda s: {"paid": True}),
        },
        entry="draft",
        edges={"draft": "approve", "approve": "pay", "pay": END},
    )
    worker = api.Runtime(domain="crm", bus=bus, store=store, graph=graph)
    web = api.Runtime(domain="crm", bus=bus, store=store, graph=graph)

    worker.submit("r1", "4192", {})
    assert worker.drain().awaiting_approval == 1
    assert web.run_row("r1")["status"] == api.AWAITING_APPROVAL
    assert [row["run_id"] for row in web.awaiting()] == ["r1"]

    resumed = web.approve("r1")
    assert resumed["status"] == api.DONE
    assert resumed["result"]["paid"] is True


def test_the_checkpoint_is_in_the_store_not_in_the_object(tmp_path):
    """So a restart does not lose every pending approval."""
    bus, store = InMemoryBus(), InMemoryStore()
    graph = Graph(
        nodes={
            "approve": Node("approve", graphs.INTERRUPT),
            "pay": Node("pay", graphs.TOOL, lambda s: {"paid": True}),
        },
        entry="approve",
        edges={"approve": "pay", "pay": END},
    )
    first = api.Runtime(domain="crm", bus=bus, store=store, graph=graph)
    first.submit("r1", "4192", {"amount": 10})
    first.drain()

    held = store.get(api.Runtime.CHECKPOINTS, "r1")
    assert held is not None, "the pause is not durable"
    assert held["run_id"] == "r1"
    assert held["next_node"] == "pay"
    assert held["state"]["amount"] == 10

    import json

    json.dumps(held), "a checkpoint that cannot be serialised cannot reach Postgres"

    # A brand-new Runtime, as a restarted worker would be.
    restarted = api.Runtime(domain="crm", bus=bus, store=store, graph=graph)
    assert restarted.approve("r1")["status"] == api.DONE


def test_approving_a_run_with_no_stored_checkpoint_says_which(tmp_path):
    bus, store = InMemoryBus(), InMemoryStore()
    graph = Graph(
        nodes={"a": Node("a", graphs.TOOL, lambda s: {})}, entry="a", edges={"a": END}
    )
    rt = api.Runtime(domain="crm", bus=bus, store=store, graph=graph)
    store.put("runs", "ghost", {"run_id": "ghost", "status": api.AWAITING_APPROVAL})

    with pytest.raises(KeyError, match="no stored checkpoint"):
        rt.approve("ghost")


def test_a_fanouts_branches_survive_the_round_trip():
    """Fan-out state holds `Outcome` dataclasses, which `json` cannot encode."""
    checkpoint = graphs.Checkpoint(
        "r1",
        "synth",
        {
            "branches": [
                graphs.Outcome("a", True, 1),
                graphs.Outcome("b", False, None, "boom"),
            ],
            "branch_status": [("a", True), ("b", False)],
            "branches_failed": ["b"],
        },
    )
    import json

    row = checkpoint.to_row()
    json.dumps(row)

    back = graphs.Checkpoint.from_row(row)
    assert [o.name for o in back.state["branches"]] == ["a", "b"]
    assert back.state["branches"][1].error == "boom"
    assert back.state["branches_failed"] == ["b"]


def test_a_checkpoint_refuses_state_it_cannot_encode():
    """Rather than stringifying it, which resumes the graph on the wrong type."""

    class Opaque:
        pass

    checkpoint = graphs.Checkpoint("r1", "next", {"handle": Opaque()})
    with pytest.raises(TypeError, match="cannot hold Opaque"):
        checkpoint.to_row()


# -- the approval gate is not reachable from the request body ------------------


def test_a_payload_carrying_the_approval_key_is_refused():
    """The interrupt was bypassable from `POST /intake`, in all twenty products.

    `graphs.APPROVED` is the string `"_approved"` and the gate reads it straight off the
    working state, which `/intake` filled from `body["payload"]` unfiltered. So
    `{"payload": {"_approved": true}}` walked a run past the interrupt into the tool
    node with no pause, no checkpoint and no row in `/approvals` - and because the path
    is in this shared module, every product had it.

    Underscore keys were stripped on the way OUT, which is what made it look handled.
    """
    rt = runtime()
    client = TestClient(api.create_app(rt))

    refused = client.post(
        "/intake", json={"run_id": "r-bad", "entity": "e1", "payload": {"_approved": True}}
    )
    assert refused.status_code == 422, refused.text
    assert "_approved" in refused.json()["detail"]
    # And nothing was recorded: a refused submit must not leave a run behind.
    assert client.get("/runs/r-bad").status_code == 404
    assert rt.bus.lag(rt.topics.tasks, rt.group) == 0


def test_the_honest_path_still_pauses():
    """The other half. A gate that refuses everything is not a working gate."""
    client = TestClient(api.create_app(runtime()))
    assert client.post("/intake", json={"run_id": "r1", "entity": "e1"}).status_code == 202
    client.post("/drain")
    assert client.get("/runs/r1").json()["status"] == api.AWAITING_APPROVAL


@pytest.mark.parametrize("key", ["_approved", "_checkpoint", "_anything"])
def test_every_underscore_key_is_refused_not_just_the_approval_one(key):
    """The reserved namespace, not one name.

    Pinning `_approved` alone would leave the next control key - or a rename of this
    one - open, and the rename is the likelier of the two.
    """
    client = TestClient(api.create_app(runtime()))
    reply = client.post("/intake", json={"run_id": "r", "entity": "e", "payload": {key: 1}})
    assert reply.status_code == 422, (key, reply.text)
    assert key in reply.json()["detail"]


def test_submit_names_every_offending_key_at_once():
    """So a caller fixes the body in one pass instead of one key per round trip."""
    rt = runtime()
    with pytest.raises(api.ControlKeyError) as raised:
        rt.submit("r", "e", {"_approved": True, "_other": 1, "fine": 2})
    assert raised.value.keys == ["_approved", "_other"]


def test_a_control_key_already_on_the_bus_is_stripped_rather_than_obeyed():
    """The second boundary. A message published directly to the broker never saw
    `submit`, and there is no caller left to return 422 to - so the key is dropped and
    the run proceeds normally, which is a pause. Rejecting the whole run here would let
    one bad publisher stop a shared worker instead."""
    rt = runtime()
    rt.bus.publish(rt.topics.tasks, "k", {"run_id": "r-direct", "payload": {"_approved": True}})
    rt.drain()
    assert rt.run_row("r-direct")["status"] == api.AWAITING_APPROVAL


def test_without_control_keys_keeps_everything_else():
    assert api.without_control_keys({"_a": 1, "b": 2, "c_": 3}) == {"b": 2, "c_": 3}


# -- resubmitting a run_id does not erase what the run did ---------------------


def test_resubmitting_a_finished_run_is_refused():
    """`Runtime.submit` wrote the row unconditionally.

    So a second `POST /intake` with a run_id that had already completed reset `status`
    to pending and dropped `visited`, `llm_calls` and `result` - the audit trail for a
    run that really happened - with no 409 and a stale checkpoint left behind. A retry
    from an at-least-once source is the normal case for a bus, not an edge one.
    """
    calls: list[str] = []
    rt = runtime(calls)
    client = TestClient(api.create_app(rt))

    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    client.post("/drain")
    client.post("/approvals/r1/approve")
    finished = client.get("/runs/r1").json()
    assert finished["status"] == api.DONE, finished

    again = client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    assert again.status_code == 409, again.text
    assert "already exists" in again.json()["detail"]
    # And the row is untouched, which is the thing worth keeping.
    assert client.get("/runs/r1").json() == finished


def test_resubmitting_a_pending_run_is_refused_too():
    """Not only a finished one: a duplicate publish of the same job is the common case,
    and running it twice costs the GPU twice."""
    client = TestClient(api.create_app(runtime()))
    assert client.post("/intake", json={"run_id": "r1", "entity": "e1"}).status_code == 202
    clash = client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    assert clash.status_code == 409
    assert "pending" in clash.json()["detail"]


def test_a_deliberate_replacement_is_allowed_and_says_so():
    client = TestClient(api.create_app(runtime()))
    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    replaced = client.post("/intake", json={"run_id": "r1", "entity": "e2", "replace": True})
    assert replaced.status_code == 202, replaced.text
    assert client.get("/runs/r1").json()["entity"] == "e2"


def test_replacing_a_paused_run_clears_its_checkpoint():
    """Otherwise `approve` on the new run resumes the old one's paused state - another
    entity's draft, approved by someone looking at this one."""
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    client.post("/drain")
    assert client.get("/runs/r1").json()["status"] == api.AWAITING_APPROVAL

    client.post("/intake", json={"run_id": "r1", "entity": "e2", "replace": True})
    assert rt.store.get(api.Runtime.CHECKPOINTS, "r1") is None
    # Approving now is a sequencing error, not a resumption of the wrong state.
    assert client.post("/approvals/r1/approve").status_code in (400, 404, 409)


def test_a_store_without_delete_is_not_a_store():
    """`Store` grew a `delete` for this, so both implementations must have one."""
    from agentplatform.adapters.postgres_store import PostgresStore

    for cls in (InMemoryStore, PostgresStore):
        assert callable(getattr(cls, "delete", None)), cls.__name__


def test_delete_is_idempotent_on_the_in_memory_store():
    store = InMemoryStore()
    store.delete("runs", "never-there")  # no raise
    store.put("runs", "r", {"a": 1})
    store.delete("runs", "r")
    assert store.get("runs", "r") is None


# -- a limit the route never bounded ------------------------------------------


@pytest.mark.parametrize("limit", ["0", "-5", "-1", "abc", "1.5", "99999", ""])
def test_a_limit_outside_the_range_is_the_callers_mistake(limit):
    """`GET /events?limit=0` returned 500.

    `ports.tail` validates `limit` - `out[-0:]` is the whole list, so `limit=0` used to
    return every event ever - but the route declared a bare `int`, so the ValueError
    came back as an internal error. The leak was turned into a crash and the route left
    to discover it. `POST /drain?limit=-1` answered 200 from the same cause: two routes
    taking the same parameter, validated in different places or not at all.
    """
    client = TestClient(api.create_app(runtime()))
    assert client.get(f"/events?limit={limit}").status_code == 422, limit
    assert client.post(f"/drain?limit={limit}").status_code == 422, limit


def test_the_default_limits_still_work():
    """A bound that rejects everything is not a bound."""
    client = TestClient(api.create_app(runtime()))
    assert client.get("/events").status_code == 200
    assert client.post("/drain").status_code == 200
    assert client.get("/events?limit=5").status_code == 200


def test_the_port_still_refuses_an_out_of_range_limit_on_its_own():
    """The route's bound is the second line, not a replacement for the first: anything
    calling `tail` directly - the projector, a script - gets the same refusal."""
    rt = runtime()
    with pytest.raises(ValueError):
        rt.bus.tail(rt.topics.events, limit=0)
    with pytest.raises(ValueError):
        rt.bus.tail(rt.topics.events, limit=-3)
