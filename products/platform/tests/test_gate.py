import pytest

from agentplatform import gate, graphs
from agentplatform.graphs import Graph, Node
from agentplatform.ports import InMemoryBus, InMemoryStore

ISSUED = {"src_a41", "src_b22", "src_c07"}


def test_a_receipted_claim_is_kept():
    r = gate.run([gate.Claim("Acme raised a round", ("src_a41",))], ISSUED)
    assert len(r.kept) == 1
    assert r.dropped == []


def test_a_claim_with_no_receipt_is_dropped():
    r = gate.run([gate.Claim("They are evaluating vendors")], ISSUED)
    assert r.kept == []
    assert r.dropped[0].reason == gate.NO_RECEIPT


def test_an_invented_citation_is_caught():
    # The failure a human reviewer misses: src_z99 looks exactly like a real id.
    r = gate.run([gate.Claim("Budget closes in December", ("src_z99",))], ISSUED)
    assert r.kept == []
    assert gate.FABRICATED in r.dropped[0].reason
    assert "src_z99" in r.dropped[0].reason


def test_one_good_receipt_does_not_excuse_one_invented_one():
    r = gate.run([gate.Claim("Mixed", ("src_a41", "src_z99"))], ISSUED)
    assert r.kept == []


def test_corroboration_requires_distinct_sources():
    same = gate.Claim("Repeated", ("src_a41", "src_a41"))
    assert gate.run([same], ISSUED, min_sources=2).dropped[0].reason == gate.UNDER_CORROBORATED
    both = gate.Claim("Corroborated", ("src_a41", "src_b22"))
    assert len(gate.run([both], ISSUED, min_sources=2).kept) == 1


def test_drop_rate_is_reported():
    r = gate.run(
        [gate.Claim("ok", ("src_a41",)), gate.Claim("bare"), gate.Claim("fake", ("src_z99",))],
        ISSUED,
    )
    assert r.drop_rate == pytest.approx(2 / 3)


def test_an_empty_run_has_no_drop_rate_rather_than_dividing_by_zero():
    assert gate.run([], ISSUED).drop_rate == 0.0


def test_min_sources_must_be_sane():
    with pytest.raises(ValueError):
        gate.run([], ISSUED, min_sources=0)


# -- where the claims came from, which is the whole question ------------------


def test_the_gate_says_the_claims_came_from_the_request():
    """All twenty READMEs said this gate "drops anything the model wrote that no tool
    receipt supports". No node in any of the twenty writes `claims` or
    `issued_receipts`: both arrive in the request body, which the same READMEs list as
    input keys fifteen lines later. So the gate filtered the caller's claims against
    the caller's own receipt list - correct arithmetic, and not a statement about the
    model. The LLM nodes write `summary` and `draft`, which the gate never reads.
    """
    state = {
        "_supplied": ("claims", "issued_receipts"),
        "claims": [{"text": "a", "receipts": ["src_1"]}, {"text": "b", "receipts": []}],
        "issued_receipts": ["src_1"],
    }
    out = gate.from_state(state)

    assert out["claims_source"] == gate.FROM_PAYLOAD
    assert out["receipts_source"] == gate.FROM_PAYLOAD
    assert out["kept_claims"] == ["a"]
    assert len(out["dropped_claims"]) == 1
    assert out["claims_checked"] == 2
    # None, not 0.5. A rate there reads as "this fraction of what the model said was
    # unsupported", and over the request body it measures nothing.
    assert out["drop_rate"] is None


def test_the_gate_reports_a_rate_when_a_node_produced_the_claims():
    """The other half: once something upstream writes them, the rate means what it says."""
    state = {
        "_supplied": ("encounter", "events"),
        "claims": [{"text": "a", "receipts": ["src_1"]}, {"text": "b", "receipts": []}],
        "issued_receipts": ["src_1"],
    }
    out = gate.from_state(state)
    assert out["claims_source"] == gate.FROM_NODES
    assert out["receipts_source"] == gate.FROM_NODES
    assert out["drop_rate"] == 0.5


def test_the_two_sources_are_reported_separately():
    """Receipts from a tool and claims from the caller is the shape worth distinguishing:
    it is a real audit of a draft, and it is still not a measurement of the model."""
    out = gate.from_state(
        {
            "_supplied": ("claims",),
            "claims": [{"text": "a", "receipts": ["src_1"]}],
            "issued_receipts": ["src_1"],
        }
    )
    assert (out["claims_source"], out["receipts_source"]) == (
        gate.FROM_PAYLOAD,
        gate.FROM_NODES,
    )
    assert out["drop_rate"] is None


def test_the_runner_records_the_callers_keys_and_does_not_return_them():
    """The marker is plumbing: present while the graph runs, absent from the result."""
    seen: list[tuple] = []

    def look(state: dict) -> dict:
        seen.append(state.get(graphs.SUPPLIED))
        return {}

    graph = Graph(nodes={"a": Node("a", graphs.TOOL, look)}, entry="a", edges={"a": graphs.END})
    out = graphs.run(graph, {"claims": [], "entity": "e"})
    assert seen == [("claims", "entity")]
    assert graphs.SUPPLIED not in out.state


def test_the_marker_cannot_be_set_from_a_request_body():
    """It is underscore-prefixed, so `Runtime.submit` refuses it - the same guard that
    closed the approval bypass. A caller setting `_supplied` to `()` would make every
    payload-sourced drop rate look like a measured one."""
    from agentplatform import api

    assert graphs.SUPPLIED.startswith("_")
    rt = api.Runtime(
        domain="d",
        bus=InMemoryBus(),
        store=InMemoryStore(),
        graph=Graph(
            nodes={"a": Node("a", graphs.TOOL, lambda s: {})},
            entry="a",
            edges={"a": graphs.END},
        ),
    )
    with pytest.raises(api.ControlKeyError):
        rt.submit("r", "e", {graphs.SUPPLIED: ()})
