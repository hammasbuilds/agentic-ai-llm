"""claims-floor agents: intake, coverage, fraud signals, settlement.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from datetime import date

from agentplatform.authority import Level, Table

from .domain import NoVersionInForceError, PolicyVersion, assess
from .ecfr import amended as _amended
from .ecfr import in_force as _in_force
from .ecfr import latest as _latest


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("fnol-intake", "claim.*", Level.WRITE)
        .grant("coverage-checker", "coverage.*", Level.WRITE)
        .grant("fraud-scorer", "claim.signals", Level.WRITE)
        .grant("fraud-scorer", "claim.declined", Level.NEVER)
        .grant("settlement-writer", "settlement.draft", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """Coverage is decided under the wording in force on the loss date."""
    if state.get("versions") is None:
        return _triage_real(state)
    versions = [
        PolicyVersion(
            v["id"],
            date.fromisoformat(v["from"]),
            date.fromisoformat(v["to"]) if v.get("to") else None,
            frozenset(v.get("perils", [])),
            frozenset(v.get("exclusions", [])),
        )
        for v in state.get("versions", [])
    ]
    try:
        coverage = assess(
            versions, date.fromisoformat(state["loss_date"]), state.get("peril", "")
        )
    except NoVersionInForceError as refused:
        return {"no_version": True, "refusal": str(refused), "summary_subject": []}
    return {
        "no_version": False,
        "covered": coverage.covered,
        "coverage_reason": coverage.reason,
        "version_id": coverage.version_id,
        "summary_subject": [coverage.version_id],
    }


def _triage_real(state: dict) -> dict:
    """The same question against real versioned regulation.

    A section with a history and a date is structurally an insurance wording
    with a history and a loss date. See :mod:`claimsfloor.ecfr`.
    """
    sections = _amended()
    if not sections:
        return {"no_version": True, "refusal": "no version history", "summary_subject": []}
    section = state.get("section") or sorted(sections)[0]
    rows = sections.get(section)
    if not rows:
        return {
            "no_version": True,
            "refusal": f"unknown section {section}",
            "summary_subject": [],
        }

    asked = (
        date.fromisoformat(state["loss_date"]) if state.get("loss_date") else rows[0].effective
    )
    correct = _in_force(section, asked)
    current = _latest(section)
    if correct is None:
        return {
            "no_version": True,
            "refusal": f"no text in force on {asked.isoformat()}",
            "summary_subject": [],
        }
    return {
        "no_version": False,
        "covered": not correct.removed,
        "coverage_reason": "read under the text in force on the loss date",
        "version_id": correct.effective.isoformat(),
        "current_version_id": current.effective.isoformat() if current else "",
        "would_have_been_wrong": bool(current and current.effective != correct.effective),
        "summary_subject": [section, correct.effective.isoformat()],
    }


def early_exit(state: dict) -> bool:
    """No wording covered that date. Never silently fall back to the latest."""
    return bool(state.get("no_version"))


def on_exit(state: dict) -> dict:
    return {"cannot_assess": True, "reason": state.get("refusal", "")}


def commit(state: dict) -> dict:
    return {"settlement.draft": state.get("draft", ""), "paid": False}


def _history(state: dict) -> list[str]:
    """Every dated version of the section. Real receipts."""
    sections = _amended()
    section = state.get("section") or (sorted(sections)[0] if sections else "")
    return [r.effective.isoformat() for r in sections.get(section, [])]


def _pinned(state: dict) -> list[str]:
    """The version actually read, and the one a naive retriever would return."""
    out = [f"read={state.get('version_id', '')}"]
    if state.get("current_version_id"):
        out.append(f"current={state['current_version_id']}")
    return out


def default_sources() -> dict:
    """Both branches read the committed eCFR version index."""
    return {"history": _history, "pinned": _pinned}
