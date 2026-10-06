"""swarm-lab agents: sweep running, metric collection, reporting.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import ToolCall, Write, conflicting_writes, duplicate_calls
from .sweep import run_trial as _run_trial


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("sweep-runner", "trial.*", Level.WRITE)
        .grant("collector", "metric.*", Level.WRITE)
        .grant("collector", "metric.estimated", Level.NEVER)
        .grant("narrator", "report.draft", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """Count, never estimate."""
    if state.get("calls") is not None:
        calls = [ToolCall(c["agent"], c["tool"], c["args"], c["seq"]) for c in state["calls"]]
        writes = [
            Write(w["agent"], w["entity"], w["field"], w["value"], w["seq"])
            for w in state.get("writes", [])
        ]
    else:
        # A real trial: N workers against the real Redis lock when one is up.
        trial = _run_trial(
            state.get("n_agents", 5),
            entities=state.get("entities", 40),
            topology=state.get("topology", "flat"),
            use_lock=state.get("use_lock", False),
        )
        calls, writes = trial.calls, trial.writes
    conflicts = conflicting_writes(writes)
    return {
        "duplicate_calls": duplicate_calls(calls),
        "conflicts": len(conflicts),
        "reportable": state.get("repeats", 0) >= 3,
        "summary_subject": [len(calls), len(writes)],
    }


def early_exit(state: dict) -> bool:
    """Fewer than three repeats is not a rate and will not be written up."""
    return not state.get("reportable", False)


def on_exit(state: dict) -> dict:
    return {"not_reportable": True, "reason": "a cell needs at least three repeats"}


def commit(state: dict) -> dict:
    return {"report.draft": state.get("draft", ""), "published": False}


def _curve(state: dict) -> list[str]:
    """The measured waste at each N, as receipts."""
    out = []
    for n in (1, 2, 5, 13):
        trial = _run_trial(n, entities=state.get("entities", 20))
        out.append(f"n{n}:duplicate_rate={trial.duplicate_rate:.3f}")
    return out


def _coordinated(state: dict) -> list[str]:
    """The same N, with a lock. The comparison the curve is meaningless without."""
    out = []
    for n in (2, 5, 13):
        trial = _run_trial(n, entities=state.get("entities", 20), use_lock=True)
        out.append(f"n{n}:calls={len(trial.calls)}:contention={trial.lock_contentions}")
    return out


def default_sources() -> dict:
    """Both branches run real trials."""
    return {"curve": _curve, "coordinated": _coordinated}
