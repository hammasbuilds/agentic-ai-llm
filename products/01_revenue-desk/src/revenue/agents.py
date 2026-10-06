"""The agents, and what each is allowed to write.

Three of the six do not call a model at all. That is not minimalism — the
qualifier scores from published rules, the forecaster does arithmetic, and the
reply classifier's one decision that matters (an opt-out) is a phrase match,
because missing one is a compliance event and a model cannot be asked to
promise it will not.
"""

from __future__ import annotations

from agentplatform import gate
from agentplatform.authority import Level, Table

from .domain import Deal, weighted_forecast

SCOUT = "scout"
ENRICHER = "enricher"
QUALIFIER = "qualifier"
WRITER = "writer"
CLASSIFIER = "reply-classifier"
ANALYST = "deal-analyst"
FORECASTER = "forecaster"


def authority() -> Table:
    """Who may write what. Default-deny; see agentplatform.authority."""
    return (
        Table()
        .grant(SCOUT, "lead.*", Level.WRITE)
        .grant(ENRICHER, "company.*", Level.WRITE)
        .grant(QUALIFIER, ("lead.score", "lead.stage"), Level.WRITE)
        .grant(WRITER, "draft.*", Level.WRITE)
        .grant(WRITER, "message.send", Level.PROPOSE)
        .grant(CLASSIFIER, ("reply.intent", "contact.opted_out"), Level.WRITE)
        .grant(ANALYST, "deal.risk_factors", Level.WRITE)
        .grant(ANALYST, ("deal.amount", "deal.close_date"), Level.PROPOSE)
    )


# Phrases that end an outreach sequence. Deliberately literal: one missed
# opt-out is a compliance event, and the asymmetry does not survive a prompt.
OPT_OUT = (
    "unsubscribe",
    "remove me",
    "take me off",
    "stop emailing",
    "do not contact",
    "don't contact",
    "not interested, remove",
)


def classify_reply(state: dict) -> dict:
    """Opt-out detection is a phrase match. Everything else can be a model."""
    body = (state.get("reply", "") or "").lower()
    if any(phrase in body for phrase in OPT_OUT):
        return {"reply.intent": "opt_out", "contact.opted_out": True}
    return {"reply.intent": "engaged" if body else "no_reply"}


def qualify(state: dict) -> dict:
    """Fit from a published weights table, so a buyer can argue with a weight."""
    signals = state.get("signals", {})
    weights = {"hiring": 0.4, "funding": 0.3, "stack_match": 0.2, "region": 0.1}
    score = sum(weights[k] for k, present in signals.items() if present and k in weights)
    return {
        "lead.score": round(score, 4),
        "lead.stage": "qualified" if score >= 0.5 else "sourced",
    }


def forecast(state: dict) -> dict:
    """Arithmetic. The model is not asked and never will be."""
    deals = [Deal(d["id"], d["amount"], d["stage"]) for d in state.get("deals", [])]
    return {"forecast": weighted_forecast(deals)}


def run_gate(state: dict) -> dict:
    """Drop any claim the tools did not actually support."""
    claims = [
        gate.Claim(c["text"], tuple(c.get("receipts", ()))) for c in state.get("claims", [])
    ]
    issued = set(state.get("issued_receipts", ()))
    result = gate.run(claims, issued, min_sources=state.get("min_sources", 1))
    return {
        "kept_claims": [c.text for c in result.kept],
        "dropped_claims": [(d.claim.text, d.reason) for d in result.dropped],
        "drop_rate": round(result.drop_rate, 4),
    }
