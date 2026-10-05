import pytest

from agentplatform import blueprint, graphs
from agentplatform.llm import Recorded


def parts(**over):
    base = dict(
        triage=lambda s: {"triaged": True},
        gather={"a": lambda s: 1, "b": lambda s: 2},
        synthesise=lambda s: {"summary": "s"},
        compose=lambda s: {"draft": "d"},
        gate=lambda s: {"kept": 1},
        commit=lambda s: {"committed": True},
    )
    base.update(over)
    return base


def test_the_pipeline_pauses_for_a_person_before_committing():
    graph = blueprint.review_pipeline(**parts())
    with pytest.raises(graphs.GraphInterruptedError) as caught:
        graphs.run(graph, {})
    assert caught.value.checkpoint.awaiting == blueprint.APPROVE
    assert caught.value.checkpoint.next_node == blueprint.COMMIT


def test_nothing_commits_without_approval():
    graph = blueprint.review_pipeline(**parts())
    with pytest.raises(graphs.GraphInterruptedError) as caught:
        graphs.run(graph, {})
    assert "committed" not in caught.value.checkpoint.state


def test_approval_commits_without_regenerating():
    calls = []
    graph = blueprint.review_pipeline(
        **parts(compose=lambda s: calls.append(1) or {"draft": "d"})
    )
    with pytest.raises(graphs.GraphInterruptedError) as caught:
        graphs.run(graph, {})
    assert len(calls) == 1
    resumed = dict(caught.value.checkpoint.state)
    resumed[graphs.APPROVED] = True
    result = graphs.run(
        graph,
        checkpoint=graphs.Checkpoint("r", caught.value.checkpoint.next_node, resumed),
    )
    assert result.state["committed"] is True
    assert len(calls) == 1


def test_an_early_exit_costs_no_generation():
    calls = []
    graph = blueprint.review_pipeline(
        **parts(
            synthesise=lambda s: calls.append("synth") or {},
            compose=lambda s: calls.append("compose") or {},
            early_exit=lambda s: s.get("refuse"),
            on_exit=lambda s: {"refused": True},
        )
    )
    result = graphs.run(graph, {"refuse": True})
    assert result.state["refused"] is True
    assert calls == []
    assert result.llm_calls == 0


def test_the_early_exit_is_not_taken_when_it_does_not_apply():
    graph = blueprint.review_pipeline(
        **parts(
            early_exit=lambda s: s.get("refuse"),
            on_exit=lambda s: {"refused": True},
        )
    )
    with pytest.raises(graphs.GraphInterruptedError):
        graphs.run(graph, {"refuse": False})


def test_an_early_exit_with_nowhere_to_go_is_refused_at_build_time():
    with pytest.raises(ValueError, match="on_exit"):
        blueprint.review_pipeline(**parts(early_exit=lambda s: True))


def test_a_failed_gather_branch_reaches_synthesis():
    seen = {}

    def boom(state):
        raise TimeoutError("source down")

    graph = blueprint.review_pipeline(
        **parts(
            gather={"ok": lambda s: 1, "dead": boom},
            synthesise=lambda s: seen.update(failed=s["branches_failed"]) or {"summary": "s"},
        )
    )
    with pytest.raises(graphs.GraphInterruptedError):
        graphs.run(graph, {})
    assert seen["failed"] == ["dead"]


def test_the_pipeline_uses_exactly_two_generations():
    graph = blueprint.review_pipeline(**parts())
    with pytest.raises(graphs.GraphInterruptedError) as caught:
        graphs.run(graph, {})
    assert caught.value.partial.llm_calls == 2


def test_the_standard_graph_wires_one_products_agents():
    """`standard_graph` is the shape nineteen products were each writing out.

    Before this, nineteen `graph.py` were byte-identical below their docstrings -
    the same `summarise`, `compose` and `build`, 589 lines of it - while the
    module's own docstring said "what differs is the judgement in agents, not
    the shape". The shape now lives here once.
    """

    class Agents:
        triage = staticmethod(lambda state: {"triaged": True})
        commit = staticmethod(lambda state: {"sent": True})
        early_exit = staticmethod(lambda state: bool(state.get("opted_out")))
        on_exit = staticmethod(lambda state: {"suppressed": True})

        @staticmethod
        def default_sources():
            return {"search": lambda state: {"hits": 1}}

    graph = blueprint.standard_graph(Agents, Recorded({}))
    # The same seven nodes review_pipeline builds, plus the exit branch.
    assert {blueprint.TRIAGE, blueprint.GATHER, blueprint.SYNTHESISE} <= set(graph.nodes)
    assert blueprint.APPROVE in graph.nodes
    assert blueprint.COMMIT in graph.nodes


def test_the_summarise_node_names_the_sources_that_died():
    """A fan-out where one branch failed must not be summarised as complete.

    The failure list goes into the prompt, so the model cannot narrate a whole
    picture from a partial one - the most expensive wrong answer these products
    can produce, because it reads as confident.
    """
    prompt = "summarise:tender-42|failed:['registry']"
    node = blueprint.summarise_node(Recorded({prompt: "two of three sources answered"}))
    out = node({"summary_subject": "tender-42", "branches_failed": ["registry"]})
    assert out["summary"] == "two of three sources answered"


def test_the_summarise_node_asks_the_same_prompt_whatever_the_failure_order():
    node = blueprint.summarise_node(Recorded({"summarise:x|failed:['a', 'b']": "ok"}))
    assert node({"summary_subject": "x", "branches_failed": ["b", "a"]})["summary"] == "ok"
