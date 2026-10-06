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

#: The caller's own keys, recorded at entry. Underscore-prefixed, so `Runtime.submit`
#: refuses it from a request body and `_public` strips it from every reply.
SUPPLIED = "_supplied"


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

    def to_row(self) -> dict:
        """A JSON-safe row, so the pause survives the process that created it.

        `Runtime` held checkpoints in a plain in-process dict, so approving a run was
        possible only from the same Python object that drained it. A web process
        sharing the bus and the store with a worker saw the row as
        `awaiting_approval`, listed it under `/approvals`, and answered
        `POST /approvals/{id}/approve` with 404 - and a restart lost every pending
        approval while the stored row still said it was waiting.

        Fan-out state holds `Outcome` dataclasses, which `json` cannot encode, so
        this converts them and **raises** on anything else rather than dropping it: a
        checkpoint that silently loses part of its state resumes a different run.
        """
        return {
            "run_id": self.run_id,
            "next_node": self.next_node,
            "state": _encodable(self.state),
        }

    @classmethod
    def from_row(cls, row: dict) -> Checkpoint:
        state = dict(row["state"])
        if "branches" in state:
            state["branches"] = [Outcome(**o) for o in state["branches"]]
        return cls(row["run_id"], row["next_node"], state)


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


def _encodable(value):
    """`value` as something `json.dumps` accepts, or a TypeError naming what it hit.

    Deliberately not `default=str`: a state field quietly stringified comes back as
    the wrong type on resume, and the graph then runs on data that looks right.
    """
    import dataclasses
    import json

    def convert(item):
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return {k: convert(v) for k, v in dataclasses.asdict(item).items()}
        if isinstance(item, dict):
            return {str(k): convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        raise TypeError(
            f"a checkpoint cannot hold {type(item).__name__}: it has to survive the "
            "process that made it, and stringifying it would resume the graph on the "
            "wrong type"
        )

    converted = convert(value)
    json.dumps(converted)  # proves it, rather than assuming it
    return converted


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
        # The approval is consumed by the resume it authorised. Resuming starts at the
        # node AFTER the interrupt, so the interrupt's own body - which is where the
        # flag used to be cleared - never runs on a resume, and `_approved` stayed true
        # for the rest of the graph. A draft -> approve -> commit -> approve -> pay
        # chain therefore executed the second gate on the first signature, reported
        # `done`, and emitted no approvals event for the gate it skipped.
        working.pop(APPROVED, None)
        working.pop("_interrupt", None)
    else:
        current = graph.entry
        working = dict(state or {})
        # The keys the CALLER supplied, recorded before any node runs. The grounding
        # gate reads `claims` and `issued_receipts` off the working state, and no node
        # in any of the twenty products writes either - so the gate was filtering the
        # request body against the request body and reporting a drop rate over it. It
        # cannot tell the difference on its own; this is how it can.
        working[SUPPLIED] = tuple(sorted(k for k in working if not k.startswith("_")))

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

    # The entry marker is plumbing, not a result. It stays in the state while the graph
    # runs - the gate reads it - and in a checkpoint, because a resume needs it; it does
    # not belong in what a caller reads back.
    working.pop(SUPPLIED, None)
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


def _compiled_node(node: Node) -> Callable:
    """One node of the declaration, as a callable LangGraph can hold.

    Each wrapper returns the *whole* merged state rather than its own update.
    `StateGraph(dict)` has no reducer, so a node returning `{"y": 1}` replaces the
    channel set instead of adding to it: a two-node graph seeded with `{"seed": 0}`
    came back as `{"y": 1}`, having dropped both the seed and the first node's
    output. Every product's state is a free-form dict, so every product lost
    everything but its last node's keys.
    """
    if node.kind == FANOUT:
        # `run` is None on a fan-out, and the old compiler substituted a no-op for
        # it - so `branches`, `branch_status` and `branches_failed` never entered the
        # state and the synthesis node downstream was never told a branch had died.
        # That is the 0% disclosure this module's docstring cites as the reason the
        # status list is handed over explicitly. Compiling it away reintroduced it.
        return lambda state: {**state, **_run_fanout(node, state)}
    if node.kind == INTERRUPT:
        # The body of an interrupt is the pause itself, which LangGraph performs with
        # `interrupt_before` on the following node rather than inside this one. The
        # node still clears the flags the pause consumed.
        def resume(state: dict) -> dict:
            carried = {k: v for k, v in state.items() if k not in (APPROVED, "_interrupt")}
            return carried

        return resume
    return lambda state: {**state, **(node.run(state) or {})}


def to_langgraph(graph: Graph, *, checkpointer: object | None = None):
    """Compile the same declaration onto langgraph, once it is installed.

    "A product describes its graph once either way" was not true of three things, and
    none of them had a test: state did not accumulate between nodes, every interrupt
    became a no-op so the approval gate vanished from the compiled graph, and every
    fan-out became a no-op so a dead branch went unreported.

    An interrupt compiles to LangGraph's `interrupt_before` on the node after it,
    which needs a checkpointer; one is supplied if the caller does not pass theirs.
    Invoke it with a `thread_id`, as LangGraph requires:

        app = to_langgraph(graph)
        config = {"configurable": {"thread_id": run_id}}
        app.invoke(state, config)   # runs up to the gate and stops
        app.invoke(None, config)    # the approval; resumes after it
    """
    try:
        from langgraph.graph import StateGraph  # noqa: PLC0415 — optional extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise LangGraphNotInstalledError(
            "langgraph is not installed; the declaration runs on agentplatform."
            "graphs.run() meanwhile. Install with: uv add langgraph"
        ) from exc

    builder = StateGraph(dict)
    for name, node in graph.nodes.items():
        builder.add_node(name, _compiled_node(node))
    builder.set_entry_point(graph.entry)

    # Where the compiled graph must stop for a person: the node each interrupt
    # leads to. A conditional edge out of an interrupt cannot be resolved at compile
    # time, so it is refused rather than silently compiled without the gate.
    pause_before: list[str] = []
    for source, target in graph.edges.items():
        if callable(target):
            builder.add_conditional_edges(source, target)
        elif target == END:
            builder.set_finish_point(source)
        else:
            builder.add_edge(source, target)
        if graph.nodes[source].kind == INTERRUPT:
            if callable(target) or target == END:
                raise ValueError(
                    f"interrupt {source!r} leads to "
                    f"{'a conditional edge' if callable(target) else 'END'}; LangGraph "
                    "pauses before a named node, so this cannot be compiled with its "
                    "gate intact"
                )
            pause_before.append(target)

    if pause_before and checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver  # noqa: PLC0415 — optional

        checkpointer = MemorySaver()
    if pause_before:
        return builder.compile(checkpointer=checkpointer, interrupt_before=pause_before)
    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
