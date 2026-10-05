"""The graph runtime: five shapes, checkpointed interrupts, no dependency.

A graph is declared as data. It runs today on the executor below, with nothing
installed, and :func:`to_langgraph` compiles the same declaration once langgraph
is present. Products describe their graph once either way.

Two of the measured findings that constrain these shapes are enforced here rather than
suggested:

- a fan-out always hands the next node the **branch status list**, because a
  silently failed branch was disclosed 0% of the time otherwise;
- a resumed run restarts at the node *after* the interrupt, because a naive
  pause-and-reinvoke wastes exactly one generation per approval.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

END = "__end__"

RULES = "rules"
TOOL = "tool"
LLM = "llm"
GATE = "gate"
FANOUT = "fanout"
INTERRUPT = "interrupt"
KINDS = (RULES, TOOL, LLM, GATE, FANOUT, INTERRUPT)

APPROVED = "_approved"


@dataclass(frozen=True)
class Outcome:
    """One branch of a fan-out."""

    name: str
    ok: bool
    value: object = None
    error: str = ""


@dataclass(frozen=True)
class Node:
    name: str
    kind: str
    run: Callable = None  # type: ignore[assignment]
    branches: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.kind!r} is not one of {KINDS}")
        if self.kind == FANOUT and not self.branches:
            raise ValueError(f"fan-out {self.name!r} has no branches")
        if self.kind not in (FANOUT, INTERRUPT) and self.run is None:
            raise ValueError(f"{self.name!r} needs a run function")


@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    next_node: str
    state: dict

    @property
    def awaiting(self) -> str:
        return self.state.get("_interrupt", "")


class GraphInterruptedError(Exception):
    """The graph paused for a person.

    Carries the checkpoint *and* the work already done. Without the second half
    a paused run reports zero cost, and the generations that produced the thing
    being approved go unaccounted for — which is precisely the run whose cost
    anyone would want to know.
    """

    def __init__(self, checkpoint: Checkpoint, partial: Result | None = None) -> None:
        super().__init__(f"awaiting approval at {checkpoint.awaiting!r}")
        self.checkpoint = checkpoint
        self.partial = partial if partial is not None else Result(dict(checkpoint.state))


class LangGraphNotInstalledError(ImportError):
    pass


@dataclass
class Graph:
    nodes: dict
    entry: str
    edges: dict
    max_steps: int = 50

    def __post_init__(self) -> None:
        if self.entry not in self.nodes:
            raise ValueError(f"entry {self.entry!r} is not a node")
        for source, target in self.edges.items():
            if source not in self.nodes:
                raise ValueError(f"edge from unknown node {source!r}")
            if isinstance(target, str) and target != END and target not in self.nodes:
                raise ValueError(f"edge to unknown node {target!r}")
        for name in self.nodes:
            if name not in self.edges:
                raise ValueError(f"node {name!r} has no outgoing edge; use END")


@dataclass
class Result:
    state: dict
    visited: list = field(default_factory=list)
    llm_calls: int = 0


def _run_fanout(node: Node, state: dict) -> dict:
    outcomes: list[Outcome] = []
    for name, fn in node.branches.items():
        try:
            outcomes.append(Outcome(name, True, fn(state)))
        except Exception as exc:  # noqa: BLE001 — a failed branch is data, not a crash
            outcomes.append(Outcome(name, False, None, f"{type(exc).__name__}: {exc}"))
    return {
        "branches": outcomes,
        # Handed to the next node explicitly. A synthesis step that is not told
        # a branch died reports a complete answer; that was measured at 0%
        # disclosure in langgraph-lab project 03.
        "branch_status": [(o.name, o.ok) for o in outcomes],
        "branches_failed": [o.name for o in outcomes if not o.ok],
    }


def run(
    graph: Graph,
    state: dict | None = None,
    *,
    run_id: str = "run",
    checkpoint: Checkpoint | None = None,
) -> Result:
    """Execute the graph, or resume it from a checkpoint.

    Resuming starts at the node *after* the interrupt, carrying the state that
    was saved. Nothing before the pause is recomputed.
    """
    if checkpoint is not None:
        current = checkpoint.next_node
        working = dict(checkpoint.state)
    else:
        current = graph.entry
        working = dict(state or {})

    result = Result(state=working)
    steps = 0
    while current != END:
        steps += 1
        if steps > graph.max_steps:
            raise RuntimeError(f"graph exceeded {graph.max_steps} steps; it is looping")
        node = graph.nodes[current]
        result.visited.append(node.name)

        if node.kind == INTERRUPT:
            if not working.get(APPROVED):
                target = graph.edges[current]
                paused = dict(working)
                paused["_interrupt"] = node.name
                result.state = paused
                raise GraphInterruptedError(
                    Checkpoint(run_id, _resolve(target, paused), paused), result
                )
            working.pop(APPROVED, None)
            working.pop("_interrupt", None)
            update: dict = {}
        elif node.kind == FANOUT:
            update = _run_fanout(node, working)
        else:
            update = node.run(working) or {}
            if node.kind == LLM:
                result.llm_calls += 1

        working.update(update)
        current = _resolve(graph.edges[node.name], working)

    result.state = working
    return result


def _resolve(target, state: dict) -> str:
    return target(state) if callable(target) else target


def loop(body: Callable, *, max_iterations: int = 2, done: Callable | None = None) -> Callable:
    """A revision loop with a hard cap.

    Capped at two by default: doubling a critique-revise loop from three to six
    iterations changed nothing on every task measured, and letting the model
    report its own completion made it quit on the first draft every time. The
    ``done`` predicate is therefore external, never the model's own verdict.
    """
    if max_iterations < 1:
        raise ValueError("a loop runs at least once")

    def _run(state: dict) -> dict:
        update: dict = {}
        working = dict(state)
        for iteration in range(max_iterations):
            update = body(working) or {}
            working.update(update)
            working["iterations"] = iteration + 1
            if done is not None and done(working):
                break
        update = dict(update)
        update["iterations"] = working["iterations"]
        return update

    return _run


def to_langgraph(graph: Graph):
    """Compile the same declaration onto langgraph, once it is installed."""
    try:
        from langgraph.graph import StateGraph  # noqa: PLC0415 — optional extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise LangGraphNotInstalledError(
            "langgraph is not installed; the declaration runs on agentplatform."
            "graphs.run() meanwhile. Install with: uv add langgraph"
        ) from exc

    builder = StateGraph(dict)
    for name, node in graph.nodes.items():
        builder.add_node(name, node.run or (lambda s: {}))
    builder.set_entry_point(graph.entry)
    for source, target in graph.edges.items():
        if callable(target):
            builder.add_conditional_edges(source, target)
        elif target == END:
            builder.set_finish_point(source)
        else:
            builder.add_edge(source, target)
    return builder.compile()
