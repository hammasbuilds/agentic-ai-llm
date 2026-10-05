"""The grounding gate: a claim without a receipt does not reach the user.

Three ways a claim fails, in the order they matter:

1. no receipt at all — the model asserted something no tool returned;
2. a receipt that does not exist — the model invented a citation id, which
   looks exactly like a real one and is the failure a human reviewer misses;
3. fewer independent sources than the product requires.

The third is the only one most systems check.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Claim:
    text: str
    receipts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dropped:
    claim: Claim
    reason: str


@dataclass
class Result:
    kept: list[Claim] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)

    @property
    def drop_rate(self) -> float:
        total = len(self.kept) + len(self.dropped)
        return 0.0 if total == 0 else len(self.dropped) / total


NO_RECEIPT = "no receipt of any kind"
FABRICATED = "cites a receipt that was never issued"
UNDER_CORROBORATED = "fewer independent sources than required"


def run(
    claims: list[Claim],
    issued: set[str],
    min_sources: int = 1,
) -> Result:
    """Check claims against the receipts the tools actually issued."""
    if min_sources < 1:
        raise ValueError("min_sources must be at least 1")
    out = Result()
    for claim in claims:
        if not claim.receipts:
            out.dropped.append(Dropped(claim, NO_RECEIPT))
            continue
        unknown = [r for r in claim.receipts if r not in issued]
        if unknown:
            out.dropped.append(Dropped(claim, f"{FABRICATED}: {', '.join(sorted(unknown))}"))
            continue
        if len(set(claim.receipts)) < min_sources:
            out.dropped.append(Dropped(claim, UNDER_CORROBORATED))
            continue
        out.kept.append(claim)
    return out


def from_state(state: dict, min_sources: int = 1) -> dict:
    """The gate as a graph node.

    Reads ``claims`` and ``issued_receipts`` from the state and writes back what
    survived, what did not and why. Identical in all twenty products, because
    "a claim needs a receipt" is not a per-domain decision.
    """
    claims = [Claim(c["text"], tuple(c.get("receipts", ()))) for c in state.get("claims", [])]
    result = run(claims, set(state.get("issued_receipts", ())), min_sources=min_sources)
    return {
        "kept_claims": [c.text for c in result.kept],
        "dropped_claims": [(d.claim.text, d.reason) for d in result.dropped],
        "drop_rate": round(result.drop_rate, 4),
    }
