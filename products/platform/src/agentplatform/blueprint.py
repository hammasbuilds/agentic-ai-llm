"""The shape all twenty products share.

Every one of them does the same seven things: decide whether this is even work
worth doing, gather evidence from several places at once, summarise it, compose
something for a person, drop whatever is not supported, wait for that person,
then commit.

What differs between products is the *judgement* at each step, never the shape.
Writing the shape twenty times would mean twenty places for the approval gate to
be subtly wrong, so it is written once here.

    graph = blueprint.review_pipeline(
        triage=classify,            # rules — no model
        gather={"search": ..., "registry": ...},
        synthesise=summarise(model),
        compose=draft(model),
        gate=drop_unreceipted,
        commit=lambda s: {"sent": True},
        early_exit=lambda s: s.get("opted_out"),
        on_exit=lambda s: {"suppressed": True},
    )
"""

from __future__ import annotations

from collections.abc import Callable

from .graphs import END, FANOUT, GATE, INTERRUPT, LLM, RULES, TOOL, Graph, Node

TRIAGE = "triage"
GATHER = "gather"
SYNTHESISE = "synthesise"
COMPOSE = "compose"
GATE_NODE = "gate"
APPROVE = "approve"
COMMIT = "commit"
EXIT = "exit"


def review_pipeline(
    *,
    triage: Callable,
    gather: dict,
    synthesise: Callable,
    compose: Callable,
    gate: Callable,
    commit: Callable,
    early_exit: Callable | None = None,
    on_exit: Callable | None = None,
) -> Graph:
    """Build the standard pipeline.

    ``early_exit`` is the cheap refusal every one of these products needs: an
    opt-out, an out-of-scope host, a closed tender, a claim with no policy in
    force. It runs before anything is gathered or generated, because the whole
    point is that it costs nothing.
    """
    if early_exit is not None and on_exit is None:
        raise ValueError("an early exit needs somewhere to go; pass on_exit")

    nodes = {
        TRIAGE: Node(TRIAGE, RULES, triage),
        GATHER: Node(GATHER, FANOUT, branches=gather),
        SYNTHESISE: Node(SYNTHESISE, LLM, synthesise),
        COMPOSE: Node(COMPOSE, LLM, compose),
        GATE_NODE: Node(GATE_NODE, GATE, gate),
        APPROVE: Node(APPROVE, INTERRUPT),
        COMMIT: Node(COMMIT, TOOL, commit),
    }
    edges = {
        TRIAGE: GATHER,
        GATHER: SYNTHESISE,
        SYNTHESISE: COMPOSE,
        COMPOSE: GATE_NODE,
        GATE_NODE: APPROVE,
        APPROVE: COMMIT,
        COMMIT: END,
    }

    if early_exit is not None:
        nodes[EXIT] = Node(EXIT, TOOL, on_exit)
        edges[EXIT] = END
        edges[TRIAGE] = lambda state: EXIT if early_exit(state) else GATHER

    return Graph(nodes=nodes, entry=TRIAGE, edges=edges)


def summarise_node(model) -> Callable:
    """Summarise what GATHER found, with the failures named.

    ``branches_failed`` goes into the prompt because a fan-out where one source
    died must not be narrated as a complete picture - the most expensive kind of
    wrong answer these products can produce, since it reads as confident.
    """

    def _run(state: dict) -> dict:
        failed = sorted(state.get("branches_failed", []))
        prompt = f"summarise:{state.get('summary_subject')}|failed:{failed}"
        completion = model.generate(prompt)
        return {"summary": completion.text, "model": completion.model}

    return _run


def compose_node(model) -> Callable:
    """Turn the summary into something a person will read and approve."""

    def _run(state: dict) -> dict:
        completion = model.generate(f"compose:{state.get('summary', '')}")
        return {"draft": completion.text, "model": completion.model}

    return _run


def standard_graph(agents, model, sources: dict | None = None) -> Graph:
    """The whole pipeline, wired to one product's ``agents`` module.

    Nineteen of the twenty products' ``graph.py`` were byte-identical below the
    docstring: the same ``summarise``, the same ``compose``, the same ``build``,
    written out nineteen times. The module's own docstring already said "what
    differs is the judgement in agents, not the shape" - so the shape belongs
    here, and a product's graph module is now the binding and nothing else.

    ``01_revenue-desk`` deliberately does NOT use this. It writes every node out
    by hand as the worked example the others were copied from, and flattening it
    into a one-line call would delete the thing it exists to show.

    ``agents`` supplies ``triage``, ``default_sources``, ``commit``,
    ``early_exit`` and ``on_exit``.
    """
    return review_pipeline(
        triage=agents.triage,
        gather=sources or agents.default_sources(),
        synthesise=summarise_node(model),
        compose=compose_node(model),
        gate=_state_gate(),
        commit=agents.commit,
        early_exit=agents.early_exit,
        on_exit=agents.on_exit,
    )


def _state_gate() -> Callable:
    # Imported here rather than at module scope: blueprint is imported by gate's
    # own consumers and a top-level import would make the cycle real.
    from . import gate

    return gate.from_state
