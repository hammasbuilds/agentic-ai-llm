"""comms-desk agents: triage, extraction, reconciliation, scheduling.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .ami import commitments as _ami_commitments
from .domain import Commitment, dedupe


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("triage", "thread.category", Level.WRITE)
        .grant("extractor", "commitment.*", Level.WRITE)
        .grant("reply-writer", "draft.*", Level.WRITE)
        .grant("reply-writer", "message.send", Level.NEVER)
        .grant("scheduler", "slot.proposed", Level.WRITE)
    )


def _commitments(state: dict) -> list[Commitment]:
    """The commitments to reconcile.

    Supplied directly by the unit tests. Otherwise read from the AMI Meeting
    Corpus, where the speaker attribution is hand-annotated ground truth.
    """
    if state.get("commitments") is not None:
        return [
            Commitment(c["id"], c["speaker"], c["text"], c["source"])
            for c in state["commitments"]
        ]
    found = _ami_commitments(limit_meetings=state.get("meetings", 4))
    return [Commitment(f"c{i}", u.key, u.text, "meeting") for i, u in enumerate(found)]


def triage(state: dict) -> dict:
    """Merge restatements of one promise; never merge across speakers."""
    items = _commitments(state)
    clusters = dedupe(items, threshold=state.get("threshold", 0.4))
    return {
        "clusters": len(clusters),
        "duplicates": len(items) - len(clusters),
        "summary_subject": sorted({c.speaker for c in items}),
    }


def early_exit(state: dict) -> bool:
    """Nothing was promised, so there is nothing to draft."""
    return not state.get("clusters")


def on_exit(state: dict) -> dict:
    return {"nothing_to_do": True}


def commit(state: dict) -> dict:
    """A draft. This product does not send, with no exception."""
    return {"draft": state.get("draft", ""), "sent": False}


def _speakers(state: dict) -> list[str]:
    """Who is on the hook. Real meeting:speaker slots, as receipts."""
    return sorted({c.speaker for c in _commitments(state)})


def _acts(state: dict) -> list[str]:
    """The commitments themselves, truncated, as evidence."""
    return sorted({c.text[:60] for c in _commitments(state)})[:40]


def default_sources() -> dict:
    """Both branches read the committed AMI annotations."""
    return {"speakers": _speakers, "acts": _acts}
