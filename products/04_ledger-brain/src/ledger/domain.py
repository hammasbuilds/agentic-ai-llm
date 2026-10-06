"""Payment-to-invoice matching that refuses rather than guesses.

The interesting subset is not the 94% that match cleanly. It is the handful
where two open invoices carry the same amount, where a confident matcher is
right about half the time and never says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Invoice:
    id: str
    amount: int  # minor units; floats do not belong in money
    reference: str = ""


@dataclass(frozen=True)
class Payment:
    id: str
    amount: int
    reference: str = ""


@dataclass
class Matching:
    matched: dict[str, str] = field(default_factory=dict)  # payment -> invoice
    ambiguous: dict[str, list[str]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)

    @property
    def ambiguity_rate(self) -> float:
        total = len(self.matched) + len(self.ambiguous) + len(self.unmatched)
        return 0.0 if total == 0 else len(self.ambiguous) / total


def match(payments: list[Payment], invoices: list[Invoice], tolerance: int = 0) -> Matching:
    """Match on reference first, then on amount, and refuse when amounts tie.

    ``tolerance`` is in minor units and absolute on purpose: a proportional
    tolerance on a large invoice is wide enough to swallow a small one whole.
    """
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    out = Matching()
    open_invoices = {inv.id: inv for inv in invoices}
    by_reference = {inv.reference: inv for inv in invoices if inv.reference}

    for payment in payments:
        if payment.reference and payment.reference in by_reference:
            invoice = by_reference[payment.reference]
            if invoice.id in open_invoices:
                out.matched[payment.id] = invoice.id
                del open_invoices[invoice.id]
                continue

        candidates = [
            inv.id
            for inv in open_invoices.values()
            if abs(inv.amount - payment.amount) <= tolerance
        ]
        if len(candidates) == 1:
            out.matched[payment.id] = candidates[0]
            del open_invoices[candidates[0]]
        elif candidates:
            out.ambiguous[payment.id] = sorted(candidates)
        else:
            out.unmatched.append(payment.id)
    return out


def equal_amount_subset(invoices: list[Invoice]) -> list[int]:
    """Amounts carried by more than one open invoice — where the damage is."""
    seen: dict[int, int] = {}
    for invoice in invoices:
        seen[invoice.amount] = seen.get(invoice.amount, 0) + 1
    return sorted(amount for amount, n in seen.items() if n > 1)


def runway_days(cash: int, daily_burn: int) -> int:
    """Whole days of cash left. Computed here so no model ever reasons about it."""
    if daily_burn <= 0:
        raise ValueError("runway is undefined without a positive burn")
    return cash // daily_burn
