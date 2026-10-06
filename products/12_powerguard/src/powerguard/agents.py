"""powerguard agents: sensing, policy, custody, resume planning.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import Job, Machine, plan, unowned_at_risk
from .machine import gpu as _gpu
from .machine import jobs as _real_jobs
from .machine import power as _real_power


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("sensor-watcher", "reading.*", Level.WRITE)
        .grant("policy-engine", "plan.*", Level.WRITE)
        .grant("job-custodian", "action.*", Level.WRITE)
        .grant("job-custodian", "process.unowned", Level.NEVER)
        .grant("incident-narrator", "event.summary", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """Plan deterministically, and never plan an action on another session's process."""
    if state.get("jobs") is not None:
        jobs = [
            Job(j["pid"], j["name"], j["kind"], j["owned"], j.get("checkpointable", False))
            for j in state["jobs"]
        ]
        machine = Machine(
            state.get("on_mains", True),
            state.get("battery_pct", 100),
            state.get("minutes_remaining", 120),
        )
    else:
        jobs = _real_jobs()
        machine = (
            _real_power()
            if state.get("on_mains") is None
            else Machine(
                state["on_mains"],
                state.get("battery_pct", 100),
                state.get("minutes_remaining", 120),
            )
        )
    actions = plan(machine, jobs)
    return {
        "on_mains": machine.on_mains,
        "actions": [(a.verb, a.target) for a in actions],
        "unowned_at_risk": [j.name for j in unowned_at_risk(jobs)],
        "summary_subject": [a.verb for a in actions],
    }


def early_exit(state: dict) -> bool:
    """Mains is on. Nothing to narrate and nothing to approve."""
    return bool(state.get("on_mains"))


def on_exit(state: dict) -> dict:
    return {"nothing_to_do": True, "reason": "on mains"}


def commit(state: dict) -> dict:
    return {"incident_note": state.get("draft", ""), "actions_taken": state.get("actions", [])}


def _running(state: dict) -> list[str]:
    """What is actually running, by pid. Real receipts from the process table."""
    return sorted(f"pid{j.pid}:{j.name}" for j in _real_jobs())


def _hardware(state: dict) -> list[str]:
    """The card and the supply, read rather than assumed."""
    card = _gpu()
    power = _real_power()
    out = [
        f"mains={power.on_mains}",
        f"battery={power.battery_pct}%",
        f"runtime={power.minutes_remaining}min",
    ]
    if card:
        out.append(f"gpu={card.name}:{card.used_mb}/{card.total_mb}MB@{card.utilisation}%")
    return out


def default_sources() -> dict:
    """Both branches read this machine."""
    return {"running": _running, "hardware": _hardware}
