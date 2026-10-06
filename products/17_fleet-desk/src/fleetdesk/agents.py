"""fleet-desk agents: intake, routing, exceptions, driver comms.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import InvalidRouteError, compare, cost, eta_minutes
from .tsplib import matrix as _matrix
from .tsplib import nearest_neighbour, optimal_tour, sweep


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("order-intake", "order.*", Level.WRITE)
        .grant("route-planner", "route.*", Level.WRITE)
        .grant("exception-triager", "exception.kind", Level.WRITE)
        .grant("exception-triager", "delivery.cancelled", Level.NEVER)
        .grant("driver-comms", "message.draft", Level.WRITE)
    )


def _instance(state: dict):
    """The routing problem.

    Supplied directly by the unit tests. Otherwise the real TSPLIB berlin52
    instance, with the solver's route being the proven optimum and the
    challenger being the kind of route a model can actually reason its way to.
    """
    if state.get("matrix") is not None:
        return (
            {tuple(k.split("->")): v for k, v in state["matrix"].items()},
            set(state.get("stops", [])),
            state.get("depot", "d"),
            state.get("solver_route", []),
            state.get("challenger_route", []),
        )
    order = [str(i) for i in optimal_tour()]
    depot = order[0]
    challenger = [str(i) for i in (state.get("challenger") or sweep())]
    challenger = [depot] + [s for s in challenger if s != depot] + [depot]
    return (
        _matrix(),
        set(order[1:]),
        depot,
        order + [depot],
        challenger,
    )


def triage(state: dict) -> dict:
    """Cost both routes on one matrix. The model never plans a route."""
    matrix, stops, depot, solver_route, challenger_route = _instance(state)
    state = {**state, "solver_route": solver_route, "challenger_route": challenger_route}
    try:
        solver = cost(state.get("solver_route", []), matrix, stops, depot)
        result = compare(
            state.get("solver_route", []),
            state.get("challenger_route", []),
            matrix,
            stops,
            depot,
        )
    except InvalidRouteError as refused:
        return {"invalid_route": True, "refusal": str(refused), "summary_subject": []}
    return {
        "invalid_route": False,
        "solver_cost": solver,
        "challenger_cost": result.challenger,
        "pct_worse": round(result.pct_worse, 4),
        "eta_minutes": eta_minutes(solver, state.get("speed_kmh", 30)),
        "summary_subject": [solver, result.challenger],
    }


def early_exit(state: dict) -> bool:
    """A route that skips or repeats a stop is not a cheaper route."""
    return bool(state.get("invalid_route"))


def on_exit(state: dict) -> dict:
    return {"rejected_route": True, "reason": state.get("refusal", "")}


def commit(state: dict) -> dict:
    return {"message.draft": state.get("draft", ""), "dispatched": False}


def _legs(state: dict) -> list[str]:
    """The legs the solver's route actually uses, as receipts."""
    _, _, _, solver_route, _ = _instance(state)
    return [f"{a}->{b}" for a, b in zip(solver_route, solver_route[1:], strict=False)][:40]


def _baselines(state: dict) -> list[str]:
    """What each construction costs on this instance, as evidence."""
    from .tsplib import tour_length

    return [
        f"optimal={tour_length(list(optimal_tour()))}",
        f"nearest_neighbour={tour_length(nearest_neighbour())}",
        f"sweep={tour_length(sweep())}",
    ]


def default_sources() -> dict:
    """Both branches read the committed TSPLIB instance."""
    return {"legs": _legs, "baselines": _baselines}
