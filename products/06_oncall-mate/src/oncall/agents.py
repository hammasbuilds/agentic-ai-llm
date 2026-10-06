"""oncall-mate agents: correlation, hypothesis, attribution, comms.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import Alert, collapse, reduction
from .logs import compression, read


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("correlator", "incident.*", Level.WRITE)
        .grant("hypothesiser", "hypothesis.*", Level.WRITE)
        .grant("runbook-selector", "action.proposed", Level.WRITE)
        .grant("runbook-selector", "action.executed", Level.NEVER)
        .grant("comms-writer", "status.draft", Level.WRITE)
    )


def _alerts(state: dict) -> list[Alert]:
    """Real log lines unless the caller supplied alerts (the unit tests do)."""
    if state.get("alerts") is not None:
        return [Alert(a["id"], a["service"], a["template"], a["at"]) for a in state["alerts"]]
    system = state.get("system", "hdfs")
    lines = [line for line in read() if line.system == system]
    # Labelled with the system the LINE came from, not the one that was asked for.
    # Both were `system`, so an alert carried the request rather than its source: with
    # the filter inverted this function returned fifteen other systems' log lines, every
    # one of them stamped `hdfs`, and nothing downstream could tell. A record that
    # cannot say where it came from cannot be audited, and the id could collide across
    # systems too - `hdfs_41` and `spark_41` are different lines with the same number.
    return [
        Alert(f"{line.system}_{line.n}", line.system, line.template, line.n * 30)
        for line in lines[: state.get("limit", 500)]
    ]


def triage(state: dict) -> dict:
    """Collapse the storm before anything reads it."""
    alerts = _alerts(state)
    incidents = collapse(alerts)
    return {
        "incidents": len(incidents),
        "reduction": round(reduction(alerts, incidents), 4),
        "summary_subject": sorted({a.service for a in alerts}),
    }


def early_exit(state: dict) -> bool:
    """No incidents, no page. Nobody is woken for quiet."""
    return not state.get("incidents")


def on_exit(state: dict) -> dict:
    return {"no_incident": True}


def commit(state: dict) -> dict:
    """A proposed action and a drafted update. Execution is human-only."""
    return {"action.proposed": state.get("draft", ""), "executed": False}


def _templates(state: dict) -> list[str]:
    """The templates this incident is built from. Real, from the real logs."""
    system = state.get("system", "hdfs")
    seen = {line.template for line in read() if line.system == system}
    return sorted(seen)[: state.get("evidence_limit", 40)]


def _compression(state: dict) -> list[str]:
    """What templating cost, as a receipt the narrator has to cite."""
    system = state.get("system", "hdfs")
    c = compression([line for line in read() if line.system == system])
    return [
        f"{system}:ratio={c.ratio:.2f}",
        f"{system}:messages_lost={c.messages_lost}",
        f"{system}:rare_lost={c.rare_lost}",
    ]


def default_sources() -> dict:
    """Both branches read the committed Loghub samples."""
    return {"templates": _templates, "compression": _compression}
