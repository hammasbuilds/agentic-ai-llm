"""One price, decided once, from every proposal at once.

Two agents that are each correct alone produce a loss together. The fix is not
a better prompt; it is that only one component writes the field.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REPRICE = "reprice"
PROMOTION = "promotion"
CLEARANCE = "clearance"


@dataclass(frozen=True)
class Proposal:
    agent: str
    kind: str
    discount_pct: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.discount_pct < 100.0:
            raise ValueError("a discount is a percentage below 100")


@dataclass
class Price:
    value: int  # minor units
    applied: Proposal | None = None
    rejected: list = field(default_factory=list)
    reason: str = ""

    @property
    def at_floor(self) -> bool:
        return self.reason == FLOOR


FLOOR = "the floor is binding; the deepest proposal would have gone below it"
NO_PROPOSALS = "no proposal; the price stands"
APPLIED = "deepest single proposal applied"


def decide(base: int, proposals: list[Proposal], floor: int) -> Price:
    """The final price.

    Discounts do not compound: the deepest single proposal wins and the rest
    are recorded as rejected, so a person can see what the system chose not to
    do. The floor is an absolute price, not a percentage — ten per cent off a
    product carrying eight per cent margin is a loss whatever a percentage
    floor says.
    """
    if base <= 0:
        raise ValueError("a base price must be positive")
    if floor <= 0 or floor > base:
        raise ValueError("the floor must be positive and at or below the base price")
    if not proposals:
        return Price(base, None, [], NO_PROPOSALS)

    ordered = sorted(proposals, key=lambda p: (-p.discount_pct, p.agent))
    deepest = ordered[0]
    candidate = round(base * (1 - deepest.discount_pct / 100))
    if candidate < floor:
        return Price(floor, deepest, ordered[1:], FLOOR)
    return Price(candidate, deepest, ordered[1:], APPLIED)


def compounded(base: int, proposals: list[Proposal]) -> int:
    """What two agents each writing the field would have produced.

    Here only so the two can be compared on the same order book. Never used to
    set a price.
    """
    value = float(base)
    for proposal in proposals:
        value *= 1 - proposal.discount_pct / 100
    return round(value)


def margin(price: int, cost: int, fee_pct: float) -> int:
    """Realised margin in minor units. Computed, never narrated."""
    if cost < 0 or not 0.0 <= fee_pct < 100.0:
        raise ValueError("cost must be positive and the fee a percentage below 100")
    return price - cost - round(price * fee_pct / 100)
