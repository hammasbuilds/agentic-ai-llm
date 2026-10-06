"""shelf-ops agents: listing, repricing, promotions, returns, suppliers.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .catalogue import breaches as _breaches
from .catalogue import load as _catalogue
from .domain import Proposal, decide, margin


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("listing-writer", "listing.draft", Level.WRITE)
        .grant("repricer", "proposal.*", Level.WRITE)
        .grant("repricer", "listing.price", Level.NEVER)
        .grant("promotions-planner", "proposal.*", Level.WRITE)
        .grant("promotions-planner", "listing.price", Level.NEVER)
        .grant("price-authority", "listing.price", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """One authority decides the price from every proposal at once."""
    proposals = [
        Proposal(p["agent"], p["kind"], p["discount_pct"]) for p in state.get("proposals", [])
    ] or [Proposal("repricer", "reprice", 10.0), Proposal("promotions", "promotion", 15.0)]

    if state.get("base"):
        base, floor = state["base"], state.get("floor", 1)
    else:
        # A real product, with the lowest price it ever sold at as the floor.
        catalogue = _catalogue()
        code = state.get("sku")
        product = next((p for p in catalogue if code in (None, p.code)), catalogue[0])
        base, floor = product.modal, product.floor
        state = {**state, "sku": product.code, "cost": state.get("cost", product.low)}

    price = decide(base, proposals, floor)
    return {
        "price": price.value,
        "at_floor": price.at_floor,
        "applied_by": price.applied.agent if price.applied else None,
        "margin": margin(price.value, state.get("cost", 0), state.get("fee_pct", 0.0)),
        "summary_subject": [price.value],
    }


def early_exit(state: dict) -> bool:
    """The floor is binding, so there is no pricing decision left to explain."""
    return bool(state.get("at_floor"))


def on_exit(state: dict) -> dict:
    return {"held_at_floor": True, "price": state.get("price")}


def commit(state: dict) -> dict:
    return {"listing.price": state.get("price"), "note": state.get("draft", "")}


def _history(state: dict) -> list[str]:
    """This product's observed prices. Real receipts from the transaction record."""
    code = state.get("sku")
    product = next((p for p in _catalogue() if p.code == code), None)
    if product is None:
        return []
    return [
        f"modal={product.modal}",
        f"min={product.low}",
        f"max={product.high}",
        f"sales={product.sales}",
    ]


def _policy(state: dict) -> list[str]:
    """What each pricing policy does across the whole catalogue."""
    result = _breaches(
        [Proposal("repricer", "reprice", 10.0), Proposal("promotions", "promotion", 15.0)]
    )
    return [
        f"single_authority_breaches={result.single_authority}",
        f"compounded_breaches={result.compounded}",
        f"attributable_to_compounding={result.only_compounded}",
    ]


def default_sources() -> dict:
    """Both branches read the committed price table."""
    return {"history": _history, "policy": _policy}
