"""revenue-desk end to end: HTTP in, bus, worker, approval, HTTP out.

No broker, no database, no model, no network.
"""

import pytest
from agentplatform import api, graphs
from agentplatform.authority import Level
from agentplatform.llm import Recorded

from revenue import agents
from revenue.app import runtime

# Built rather than written out: the keys are the prompt the fake model is keyed by,
# and spelled literally they are 99 and 103 characters, which `ruff format` collapses
# onto one line and `ruff check` then rejects at this package's 96-column limit. The
# two tools disagreed about the same file until the keys stopped being long.
_WHOLE = "They are hiring three AI engineers."
_PARTIAL = "Registry lookup failed; partial picture."
_ALL_SOURCES = "['src_a41', 'src_b22', 'src_c07']"
_MINUS_REGISTRY = "['src_a41', 'src_c07']"

SCRIPT = {
    f"summarise:{_ALL_SOURCES}|failed:[]": _WHOLE,
    f"summarise:{_MINUS_REGISTRY}|failed:['registry']": _PARTIAL,
    f"draft:{_WHOLE}": "Hello — saw you are hiring.",
    f"draft:{_PARTIAL}": "Hello — a shorter note.",
}


def sources(fail_registry: bool = False):
    def registry(state):
        if fail_registry:
            raise TimeoutError("registry unreachable")
        return ["src_b22"]

    return {"web_search": lambda s: ["src_a41", "src_c07"], "registry": registry}


def payload(**extra) -> dict:
    base = {
        "reply": "sounds interesting, tell me more",
        "signals": {"hiring": True, "funding": True, "stack_match": True},
        "issued_receipts": ["src_a41", "src_b22", "src_c07"],
        "claims": [
            {"text": "They are hiring three AI engineers.", "receipts": ["src_a41"]},
            {"text": "They are evaluating vendors this quarter.", "receipts": []},
        ],
    }
    base.update(extra)
    return base


def test_the_whole_product_runs_end_to_end():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    assert fastapi
    model = Recorded(SCRIPT)
    rt = runtime(model, sources())
    client = TestClient(api.create_app(rt))

    accepted = client.post(
        "/intake", json={"run_id": "r1", "entity": "4192", "payload": payload()}
    )
    assert accepted.status_code == 202
    assert model.calls == []  # nothing has touched the model yet

    assert rt.drain() == 1
    row = client.get("/runs/r1").json()
    assert row["status"] == api.AWAITING_APPROVAL
    assert row["awaiting"] == "approve"

    done = client.post("/approvals/r1/approve").json()
    assert done["status"] == api.DONE
    assert done["result"]["sent"] is True
    assert done["llm_calls"] == 2


def test_the_draft_is_not_regenerated_across_the_approval():
    model = Recorded(SCRIPT)
    rt = runtime(model, sources())
    rt.submit("r1", "4192", payload())
    rt.drain()
    before = list(model.calls)
    rt.approve("r1")
    assert model.calls == before


def test_an_opt_out_leaves_the_graph_before_anything_is_drafted():
    model = Recorded(SCRIPT)
    rt = runtime(model, sources())
    rt.submit("r1", "4192", payload(reply="please remove me from this list"))
    rt.drain()
    row = rt.run_row("r1")
    assert row["status"] == api.DONE
    assert row["result"]["suppressed"] is True
    assert row["result"]["contact.opted_out"] is True
    assert model.calls == []  # no draft, no send, no model call


def test_a_failed_enrichment_branch_reaches_synthesis():
    model = Recorded(SCRIPT)
    rt = runtime(model, sources(fail_registry=True))
    rt.submit("r1", "4192", payload(issued_receipts=["src_a41", "src_c07"]))
    rt.drain()
    row = rt.run_row("r1")
    assert row["status"] == api.AWAITING_APPROVAL
    # The prompt that was scripted is the one naming the failed branch.
    assert any("failed:['registry']" in c for c in model.calls)


def test_an_unreceipted_claim_never_reaches_the_approver():
    model = Recorded(SCRIPT)
    rt = runtime(model, sources())
    rt.submit("r1", "4192", payload())
    rt.drain()
    state = rt.checkpoint("r1").state
    assert state["kept_claims"] == ["They are hiring three AI engineers."]
    assert state["dropped_claims"][0][0] == "They are evaluating vendors this quarter."
    assert state["drop_rate"] == 0.5


def test_the_qualifier_scores_from_published_weights():
    assert agents.qualify({"signals": {"hiring": True, "funding": True}})["lead.score"] == 0.7


def test_the_forecast_is_arithmetic_not_a_model_call():
    out = agents.forecast({"deals": [{"id": "d1", "amount": 1000, "stage": "closing"}]})
    assert out["forecast"] == 800.0


def test_the_writer_may_draft_but_only_propose_a_send():
    table = agents.authority()
    assert table.level_for(agents.WRITER, "draft.body") is Level.WRITE
    assert table.level_for(agents.WRITER, "message.send") is Level.PROPOSE


def test_the_enricher_may_never_touch_a_deal():
    assert agents.authority().level_for(agents.ENRICHER, "deal.close_date") is Level.NEVER


def test_every_graph_shape_appears_in_this_product():
    graph = runtime(Recorded(SCRIPT), sources()).graph
    kinds = {n.kind for n in graph.nodes.values()}
    assert kinds == {
        graphs.RULES,
        graphs.FANOUT,
        graphs.LLM,
        graphs.GATE,
        graphs.INTERRUPT,
        graphs.TOOL,
    }
