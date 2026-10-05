import pytest

from agentplatform import graphs
from agentplatform.graphs import (
    APPROVED,
    END,
    INTERRUPT,
    RULES,
    Checkpoint,
    Graph,
    GraphInterruptedError,
    Node,
    run,
)


def linear_graph(calls):
    return Graph(
        nodes={
            "route": Node("route", graphs.RULES, lambda s: {"routed": True}),
            "draft": Node(
                "draft", graphs.LLM, lambda s: calls.append("draft") or {"draft": "x"}
            ),
            "gate": Node("gate", graphs.GATE, lambda s: {"kept": 1}),
            "approve": Node("approve", graphs.INTERRUPT),
            "send": Node("send", graphs.TOOL, lambda s: {"sent": True}),
        },
        entry="route",
        edges={
            "route": "draft",
            "draft": "gate",
            "gate": "approve",
            "approve": "send",
            "send": END,
        },
    )


def test_a_linear_graph_runs_to_the_end_when_nothing_pauses():
    graph = Graph(
        nodes={"a": Node("a", graphs.RULES, lambda s: {"n": 1})},
        entry="a",
        edges={"a": END},
    )
    result = graphs.run(graph)
    assert result.state["n"] == 1
    assert result.visited == ["a"]


def test_an_interrupt_pauses_and_carries_a_checkpoint():
    with pytest.raises(GraphInterruptedError) as caught:
        graphs.run(linear_graph([]), run_id="run_1")
    checkpoint = caught.value.checkpoint
    assert checkpoint.awaiting == "approve"
    assert checkpoint.next_node == "send"
    assert checkpoint.state["draft"] == "x"


def test_resuming_does_not_regenerate_what_was_already_produced():
    # langgraph-lab project 04: a naive pause-and-reinvoke costs exactly one
    # wasted drafting call per approval. This asserts it costs none.
    calls = []
    graph = linear_graph(calls)
    with pytest.raises(GraphInterruptedError) as caught:
        graphs.run(graph, run_id="run_1")
    assert calls == ["draft"]

    resumed = dict(caught.value.checkpoint.state)
    resumed[graphs.APPROVED] = True
    result = graphs.run(
        graph,
        run_id="run_1",
        checkpoint=graphs.Checkpoint("run_1", caught.value.checkpoint.next_node, resumed),
    )
    assert result.state["sent"] is True
    assert calls == ["draft"]


def test_llm_calls_are_counted():
    graph = Graph(
        nodes={
            "a": Node("a", graphs.LLM, lambda s: {}),
            "b": Node("b", graphs.RULES, lambda s: {}),
        },
        entry="a",
        edges={"a": "b", "b": END},
    )
    assert graphs.run(graph).llm_calls == 1


def test_a_fanout_reports_the_branch_that_failed():
    def boom(state):
        raise TimeoutError("firecrawl gave up")

    graph = Graph(
        nodes={
            "enrich": Node(
                "enrich",
                graphs.FANOUT,
                branches={
                    "search": lambda s: ["src_a41", "src_c07"],
                    "registry": lambda s: ["src_b22"],
                    "news": boom,
                },
            ),
        },
        entry="enrich",
        edges={"enrich": END},
    )
    result = graphs.run(graph)
    assert result.state["branches_failed"] == ["news"]
    assert dict(result.state["branch_status"]) == {
        "search": True,
        "registry": True,
        "news": False,
    }


def test_the_next_node_cannot_miss_a_failed_branch():
    # langgraph-lab project 03: a silently failed branch was disclosed 0% of
    # the time. The status list is in the state, not in a prompt.
    seen = {}
    graph = Graph(
        nodes={
            "enrich": Node("enrich", graphs.FANOUT, branches={"a": lambda s: 1, "b": _boom}),
            "synthesise": Node(
                "synthesise",
                graphs.LLM,
                lambda s: seen.update(failed=s["branches_failed"]) or {},
            ),
        },
        entry="enrich",
        edges={"enrich": "synthesise", "synthesise": END},
    )
    graphs.run(graph)
    assert seen["failed"] == ["b"]


def _boom(state):
    raise RuntimeError("dead")


def test_a_conditional_edge_routes_on_state():
    graph = Graph(
        nodes={
            "check": Node("check", graphs.RULES, lambda s: {"ok": s.get("ok", False)}),
            "happy": Node("happy", graphs.TOOL, lambda s: {"path": "happy"}),
            "sad": Node("sad", graphs.TOOL, lambda s: {"path": "sad"}),
        },
        entry="check",
        edges={"check": lambda s: "happy" if s["ok"] else "sad", "happy": END, "sad": END},
    )
    assert graphs.run(graph, {"ok": True}).state["path"] == "happy"
    assert graphs.run(graph, {"ok": False}).state["path"] == "sad"


def test_a_revision_loop_is_capped():
    calls = []
    body = graphs.loop(lambda s: calls.append(1) or {"draft": len(calls)}, max_iterations=2)
    out = body({})
    assert len(calls) == 2
    assert out["iterations"] == 2


def test_a_loop_stops_early_on_an_external_predicate():
    calls = []
    body = graphs.loop(
        lambda s: calls.append(1) or {"score": 9},
        max_iterations=5,
        done=lambda s: s["score"] >= 9,
    )
    body({})
    assert len(calls) == 1


def test_a_loop_of_zero_iterations_is_refused():
    with pytest.raises(ValueError):
        graphs.loop(lambda s: {}, max_iterations=0)


def test_a_runaway_graph_is_stopped():
    graph = Graph(
        nodes={"a": Node("a", graphs.RULES, lambda s: {})},
        entry="a",
        edges={"a": "a"},
        max_steps=5,
    )
    with pytest.raises(RuntimeError, match="looping"):
        graphs.run(graph)


def test_a_graph_with_a_dangling_edge_is_refused_at_build_time():
    with pytest.raises(ValueError, match="unknown node"):
        Graph(
            nodes={"a": Node("a", graphs.RULES, lambda s: {})},
            entry="a",
            edges={"a": "nowhere"},
        )


def test_a_node_with_no_outgoing_edge_is_refused():
    with pytest.raises(ValueError, match="no outgoing edge"):
        Graph(
            nodes={
                "a": Node("a", graphs.RULES, lambda s: {}),
                "b": Node("b", graphs.RULES, lambda s: {}),
            },
            entry="a",
            edges={"a": "b"},
        )


def test_an_unknown_node_kind_is_refused():
    with pytest.raises(ValueError):
        Node("a", "vibes", lambda s: {})


def test_a_fanout_with_no_branches_is_refused():
    with pytest.raises(ValueError):
        Node("a", graphs.FANOUT)


def test_one_signature_opens_one_gate():
    """Resume starts at the node AFTER the interrupt, so the interrupt's own body —
    which is where `_approved` was cleared — never ran on a resume, and the flag stayed
    true for the rest of the graph.

    A draft → approve → commit → approve → pay chain therefore executed the second gate
    on the first signature, reported `done`, and emitted no approvals event for the gate
    it skipped. This is the platform's advertised safety primitive; no shipped product
    builds two interrupts yet, which is why nothing caught it.
    """
    log: list[str] = []

    def step(name: str):
        def go(_state: dict) -> dict:
            log.append(name)
            return {name: True}

        return go

    graph = Graph(
        entry="a",
        nodes={
            "a": Node("a", RULES, run=step("a")),
            "approve1": Node("approve1", INTERRUPT),
            "b": Node("b", RULES, run=step("b")),
            "approve2": Node("approve2", INTERRUPT),
            "pay": Node("pay", RULES, run=step("PAID")),
        },
        edges={
            "a": "approve1",
            "approve1": "b",
            "b": "approve2",
            "approve2": "pay",
            "pay": END,
        },
    )

    signatures: list[str] = []
    checkpoint = None
    for _ in range(6):
        try:
            run(graph, {} if checkpoint is None else None, checkpoint=checkpoint)
        except GraphInterruptedError as paused:
            signatures.append(paused.checkpoint.awaiting)
            resumed = dict(paused.checkpoint.state)
            resumed[APPROVED] = True
            checkpoint = Checkpoint(
                paused.checkpoint.run_id, paused.checkpoint.next_node, resumed
            )
            continue
        break

    assert signatures == ["approve1", "approve2"], signatures
    assert log == ["a", "b", "PAID"]
