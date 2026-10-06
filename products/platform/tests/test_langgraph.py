"""`to_langgraph` against the runtime it claims to be equivalent to.

The README says "a product describes its graph once either way". That was untrue of
three things at once, and `to_langgraph` had no test of any kind:

1. **State did not accumulate.** `StateGraph(dict)` has no reducer, so a node
   returning its own update replaced the channel set rather than adding to it. A
   two-node graph seeded with `{"seed": 0}` came back as `{"y": 1}`, having dropped
   the seed and the first node's output. Every product's state is a free-form dict.
2. **Every interrupt became a no-op.** An interrupt node has `run is None`, and the
   compiler substituted `lambda s: {}` for a missing `run`. The approval gate -- the
   reason this package exists -- was compiled out, and the graph ran straight
   through to the node behind it.
3. **Every fan-out became a no-op** for the same reason, so `branch_status` never
   entered the state and the synthesis node downstream was never told a branch had
   died. That is precisely the 0% disclosure the module docstring cites as the
   reason the status list is handed over explicitly.

langgraph is an optional extra, so these skip when it is absent -- naming the
package, not pretending the feature is untested for some other reason.
"""

from __future__ import annotations

import pytest

from agentplatform import graphs
from agentplatform.graphs import END, Graph, Node

langgraph = pytest.importorskip(
    "langgraph", reason="langgraph is not installed (pip install 'agentplatform[langgraph]')"
)

CONFIG = {"configurable": {"thread_id": "t"}}


def _ok(state):
    return "fine"


def _dead(state):
    raise RuntimeError("branch died")


def _gated_graph() -> Graph:
    """Draft, a human gate, a payment, a fan-out, a synthesis. All five features."""
    return Graph(
        nodes={
            "draft": Node("draft", graphs.RULES, lambda s: {"draft": "pay 100"}),
            "approve": Node("approve", graphs.INTERRUPT),
            "pay": Node("pay", graphs.TOOL, lambda s: {"paid": True}),
            "spread": Node("spread", graphs.FANOUT, branches={"a": _ok, "b": _dead}),
            "synth": Node("synth", graphs.RULES, lambda s: {"told": s.get("branch_status")}),
        },
        entry="draft",
        edges={
            "draft": "approve",
            "approve": "pay",
            "pay": "spread",
            "spread": "synth",
            "synth": END,
        },
    )


# -- 1. state ---------------------------------------------------------------


def test_state_accumulates_across_nodes_as_it_does_in_the_runtime():
    graph = Graph(
        nodes={
            "a": Node("a", graphs.RULES, lambda s: {"x": 1}),
            "b": Node("b", graphs.RULES, lambda s: {"y": s.get("x", "MISSING")}),
        },
        entry="a",
        edges={"a": "b", "b": END},
    )
    seed = {"seed": 0}
    assert graphs.run(graph, dict(seed)).state == {"seed": 0, "x": 1, "y": 1}
    assert graphs.to_langgraph(graph).invoke(dict(seed)) == {"seed": 0, "x": 1, "y": 1}


def test_a_node_can_read_what_an_earlier_node_wrote():
    """It could not. The second node saw `MISSING` where the first had written."""
    graph = Graph(
        nodes={
            "a": Node("a", graphs.RULES, lambda s: {"x": 1}),
            "b": Node("b", graphs.RULES, lambda s: {"y": s.get("x", "MISSING")}),
        },
        entry="a",
        edges={"a": "b", "b": END},
    )
    assert graphs.to_langgraph(graph).invoke({})["y"] == 1


# -- 2. the approval gate ---------------------------------------------------


def test_the_compiled_graph_stops_at_the_gate():
    app = graphs.to_langgraph(_gated_graph())
    first = app.invoke({"seed": 0}, CONFIG)

    assert app.get_state(CONFIG).next == ("pay",), (
        "it must stop before the node behind the gate"
    )
    assert "paid" not in first, "the payment ran without anyone approving it"
    assert first["draft"] == "pay 100"


def test_the_run_continues_past_the_gate_only_when_invoked_again():
    app = graphs.to_langgraph(_gated_graph())
    app.invoke({"seed": 0}, CONFIG)
    done = app.invoke(None, CONFIG)

    assert done["paid"] is True
    assert done["seed"] == 0, "and the state from before the pause is still there"
    assert graphs.APPROVED not in done
    assert "_interrupt" not in done


def test_two_threads_hold_separate_pauses():
    """A gate is per run. One approval must not release another run's payment."""
    app = graphs.to_langgraph(_gated_graph())
    one = {"configurable": {"thread_id": "one"}}
    two = {"configurable": {"thread_id": "two"}}
    app.invoke({"seed": 1}, one)
    app.invoke({"seed": 2}, two)

    app.invoke(None, one)
    assert app.get_state(one).next == ()
    assert app.get_state(two).next == ("pay",), "the other run is still waiting"


def test_an_interrupt_that_cannot_keep_its_gate_is_refused():
    """Rather than compiled without it.

    LangGraph pauses before a *named* node. An interrupt whose outgoing edge is
    conditional, or which leads straight to END, has no such node - and compiling
    it anyway produces a graph with no gate in it, which is the failure this whole
    file is about. It raises instead.
    """
    conditional = Graph(
        nodes={
            "approve": Node("approve", graphs.INTERRUPT),
            "pay": Node("pay", graphs.TOOL, lambda s: {"paid": True}),
        },
        entry="approve",
        edges={"approve": lambda s: "pay", "pay": END},
    )
    with pytest.raises(ValueError, match="conditional edge"):
        graphs.to_langgraph(conditional)

    terminal = Graph(
        nodes={"approve": Node("approve", graphs.INTERRUPT)},
        entry="approve",
        edges={"approve": END},
    )
    with pytest.raises(ValueError, match="END"):
        graphs.to_langgraph(terminal)


# -- 3. the fan-out ---------------------------------------------------------


def test_a_dead_branch_is_reported_to_the_node_that_synthesises():
    app = graphs.to_langgraph(_gated_graph())
    app.invoke({"seed": 0}, CONFIG)
    done = app.invoke(None, CONFIG)

    assert done["branch_status"] == [("a", True), ("b", False)]
    assert done["branches_failed"] == ["b"]
    assert done["told"] == [("a", True), ("b", False)], (
        "the synthesis node was handed the status list, not left to assume success"
    )


def test_the_fanout_compiles_to_the_same_outcome_as_the_runtime():
    graph = Graph(
        nodes={
            "spread": Node("spread", graphs.FANOUT, branches={"a": _ok, "b": _dead}),
            "synth": Node("synth", graphs.RULES, lambda s: {"told": s.get("branch_status")}),
        },
        entry="spread",
        edges={"spread": "synth", "synth": END},
    )
    direct = graphs.run(graph, {}).state
    compiled = graphs.to_langgraph(graph).invoke({})
    for key in ("branch_status", "branches_failed", "told"):
        assert compiled[key] == direct[key], key


def test_a_branch_that_raises_does_not_crash_the_compiled_graph():
    graph = Graph(
        nodes={
            "spread": Node("spread", graphs.FANOUT, branches={"b": _dead}),
            "after": Node("after", graphs.RULES, lambda s: {"reached": True}),
        },
        entry="spread",
        edges={"spread": "after", "after": END},
    )
    out = graphs.to_langgraph(graph).invoke({})
    assert out["reached"] is True
    assert out["branches_failed"] == ["b"]
    assert "RuntimeError: branch died" in out["branches"][0].error
