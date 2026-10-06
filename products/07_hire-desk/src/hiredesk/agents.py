"""hire-desk agents: parsing, redaction, blind scoring, fairness.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import blind_view, leaks
from .leaks import audit as _audit
from .leaks import conversations as _conversations
from .leaks import leak_rate as _leak_rate
from .leaks import redact_exact, survivors


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("cv-parser", "candidate.*", Level.WRITE)
        .grant("redactor", "redacted_view", Level.WRITE)
        .grant("scorer", "score.*", Level.WRITE)
        .grant("scorer", "candidate.name", Level.NEVER)
        .grant("fairness-auditor", "audit.*", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """Redact, then prove the redaction held before anything scores."""
    if state.get("cv") is None:
        return _triage_real(state)
    blind = blind_view(state["cv"])
    survived = leaks(blind, state.get("secrets", []))
    return {
        "redacted_view": blind.view,
        "removed": blind.removed,
        "leaks": survived,
        "summary_subject": sorted(blind.view),
    }


def _triage_real(state: dict) -> dict:
    """The same barrier, on a real document with real names in it.

    A CV corpus is not on this machine, and inventing CVs would measure the
    invention. Real conversation is a document with names used naturally, which
    is the property that matters: redaction has to remove a person, not a
    string. See :mod:`hiredesk.leaks`.
    """
    corpus = _conversations()
    index = state.get("document", 0) % len(corpus)
    conversation = corpus[index]
    redacted, removed = redact_exact(conversation.text, conversation.speakers)
    survived = survivors(redacted, conversation.speakers)
    return {
        "redacted_view": {"text": redacted[:2000]},
        "removed": [f"{n} occurrences" for n in (removed,)],
        "leaks": [f"{s.speaker}->{s.survived} x{s.occurrences}" for s in survived],
        "summary_subject": sorted(conversation.speakers),
    }


def early_exit(state: dict) -> bool:
    """Something identifying survived. Scoring now would not be blind."""
    return bool(state.get("leaks"))


def on_exit(state: dict) -> dict:
    return {"refused_to_score": True, "leaked": state.get("leaks", [])}


def commit(state: dict) -> dict:
    return {"interview_kit": state.get("draft", ""), "decision": None}


def _barrier(state: dict) -> list[str]:
    """What redaction removed, and what survived it. Real receipts."""
    results = _audit()
    return [
        f"conv{r.conversation}:removed={r.exact_removed}:leaks={len(r.leaks)}" for r in results
    ]


def _rate(state: dict) -> list[str]:
    """The measured leak rate across the corpus."""
    return [f"leak_rate={_leak_rate():.4f}"]


def default_sources() -> dict:
    """Both branches read the committed conversation corpus."""
    return {"barrier": _barrier, "rate": _rate}
