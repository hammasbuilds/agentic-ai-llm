"""comms-desk end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.
"""

import pytest
from agentplatform import api, blueprint
from agentplatform.authority import Level
from agentplatform.llm import Recorded

from comms import agents
from comms.app import runtime

SUMMARY = "A short factual summary."
DRAFT = "The drafted output."


def script(for_payload: dict) -> dict:
    """Exactly the prompts this run will produce, and no others.

    Derived from the payload rather than pasted, because Recorded raises on an
    unscripted prompt — which is what stops a test quietly reaching a real model.
    Triage runs before the fan-out, so the subject is the same whether or not a
    branch dies.
    """
    subject = agents.triage(for_payload).get("summary_subject")
    return {
        f"summarise:{subject}|failed:[]": SUMMARY,
        f"summarise:{subject}|failed:['beta']": SUMMARY,
        f"compose:{SUMMARY}": DRAFT,
    }


def sources(fail_beta: bool = False):
    def beta(state):
        if fail_beta:
            raise TimeoutError("source down")
        return ["src_b22"]

    return {"alpha": lambda s: ["src_a41"], "beta": beta}


def payload(**extra) -> dict:
    base = {
        "commitments": [
            {
                "id": "c1",
                "speaker": "ayesha",
                "source": "meeting",
                "text": "I will send the revised pricing sheet to the client before Friday",
            },
            {
                "id": "c2",
                "speaker": "ayesha",
                "source": "email",
                "text": "Sending the revised pricing sheet over to the client by Friday",
            },
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }
    base.update(extra)
    return base


def test_the_product_runs_end_to_end():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    model = Recorded(script(payload()))
    rt = runtime(model, sources())
    client = TestClient(api.create_app(rt))

    accepted = client.post(
        "/intake", json={"run_id": "r1", "entity": "e1", "payload": payload()}
    )
    assert accepted.status_code == 202
    assert model.calls == []  # the queue accepted it; the GPU has not been touched

    assert rt.drain() == 1
    paused = client.get("/runs/r1").json()
    assert paused["status"] == api.AWAITING_APPROVAL
    assert paused["awaiting"] == blueprint.APPROVE
    assert paused["llm_calls"] == 2  # already spent, and reported before resuming

    done = client.post("/approvals/r1/approve").json()
    assert done["status"] == api.DONE
    assert done["llm_calls"] == 2  # resuming added none


def test_nothing_is_regenerated_across_the_approval():
    model = Recorded(script(payload()))
    rt = runtime(model, sources())
    rt.submit("r1", "e1", payload())
    rt.drain()
    before = list(model.calls)
    rt.approve("r1")
    assert model.calls == before


def test_the_early_exit_costs_no_generation():
    model = Recorded(script(payload()))
    rt = runtime(model, sources())
    rt.submit("r1", "e1", payload(**{"commitments": []}))
    rt.drain()
    row = rt.run_row("r1")
    assert row["status"] == api.DONE
    assert row["result"]["nothing_to_do"] is True
    assert model.calls == []
    assert row["llm_calls"] == 0


def test_a_failed_gather_branch_is_disclosed_to_synthesis():
    model = Recorded(script(payload()))
    rt = runtime(model, sources(fail_beta=True))
    rt.submit("r1", "e1", payload())
    rt.drain()
    assert any("failed:['beta']" in c for c in model.calls)


def test_an_unreceipted_claim_never_reaches_the_approver():
    model = Recorded(script(payload()))
    rt = runtime(model, sources())
    rt.submit("r1", "e1", payload())
    rt.drain()
    state = rt.checkpoint("r1").state
    assert state["kept_claims"] == ["Backed by a real receipt."]
    assert state["dropped_claims"][0][0] == "Asserted with nothing behind it."
    # One of two dropped, with `claims_checked` as the denominator that says so.
    assert state["claims_checked"] == 2
    # `drop_rate` is None, and that is the finding. This asserted 0.5 - a rate over
    # `claims`, a key this run supplied in its own payload. Half of what the CALLER
    # sent was unreceipted; nothing here measures what the model wrote, and the gate
    # says so instead of publishing a figure that reads as if it did.
    assert state["drop_rate"] is None
    assert state["claims_source"] == "payload"


def test_the_authority_table_is_default_deny():
    assert agents.authority().level_for("nobody", "anything") is Level.NEVER
