"""How many model workers this GPU can actually run.

The bus can have twelve partitions. The consumer group that calls the model
cannot, because there is one card and one model instance. Getting this wrong is
the most common way a local agent system falls over at concurrency three.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Gpu:
    """What is physically present."""

    total_mb: int
    model_mb: int
    kv_cache_mb_per_slot: int

    def __post_init__(self) -> None:
        if self.model_mb >= self.total_mb:
            raise ValueError("the model does not fit on this card")
        if self.kv_cache_mb_per_slot < 1:
            raise ValueError("a slot needs some KV cache")

    @property
    def max_slots(self) -> int:
        """Concurrent generations this card supports. Never zero; never a guess."""
        free = self.total_mb - self.model_mb
        return max(1, free // self.kv_cache_mb_per_slot)


@dataclass(frozen=True)
class Decision:
    admitted: bool
    reason: str = ""
    #: Handle for the reservation this admission holds, so the caller can settle it
    #: against what the generation actually cost. ``0`` on a refusal.
    reservation: int = 0


ADMITTED = Decision(True)


class Controller:
    """Admission control in front of the model, not inside it.

    Checked before the message is handed to a worker, so a tenant over budget
    costs nothing rather than costing a generation that is then discarded.

    An admission **reserves** the estimate and a release **settles** it against what
    the generation really cost. It used to only reserve: ``admit`` added
    ``len(prompt.split()) + max_tokens`` to the tenant's usage and nothing ever
    corrected it, so ``used()`` was a sum of worst cases reported as consumption. A
    19-word prompt answered in four tokens was charged 515 - 129 times its cost - and
    a 100,000-token daily budget allowed 194 calls where the real usage allows
    25,000. A cache hit, which costs nothing at all, was charged the full estimate.

    Usage is reported in three parts, because they are three different claims:
    ``settled`` was measured, ``estimated`` is an estimate nothing ever reconciled,
    and ``reserved`` is held by generations still running.
    """

    def __init__(self, gpu: Gpu, daily_token_budget: dict[str, int] | None = None) -> None:
        self.gpu = gpu
        self._budget = dict(daily_token_budget or {})
        self._settled: dict[str, int] = {}
        self._estimated: dict[str, int] = {}
        #: reservation id -> (tenant, tokens reserved)
        self._open: dict[int, tuple[str, int]] = {}
        self._next_reservation = 0

    @property
    def in_flight(self) -> int:
        return len(self._open)

    def settled(self, tenant: str) -> int:
        """Tokens this tenant measurably consumed."""
        return self._settled.get(tenant, 0)

    def estimated(self, tenant: str) -> int:
        """Tokens charged as an estimate that was never reconciled.

        A generation that raised, or a caller that released without saying what it
        cost. Kept charged, because the safe assumption about an unmeasured call is
        that it was not free - but kept separate, so ``used`` can be read for what
        part of it is actually known.
        """
        return self._estimated.get(tenant, 0)

    def reserved(self, tenant: str) -> int:
        """Tokens held by this tenant's generations that have not finished."""
        return sum(tokens for who, tokens in self._open.values() if who == tenant)

    def used(self, tenant: str) -> int:
        """What the budget is checked against: measured, estimated and in flight."""
        return self.settled(tenant) + self.estimated(tenant) + self.reserved(tenant)

    def admit(self, tenant: str, estimated_tokens: int) -> Decision:
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens cannot be negative")
        if self.in_flight >= self.gpu.max_slots:
            return Decision(False, f"all {self.gpu.max_slots} model slots busy")
        limit = self._budget.get(tenant)
        if limit is not None and self.used(tenant) + estimated_tokens > limit:
            return Decision(
                False,
                f"{tenant} would exceed its daily budget "
                f"({self.used(tenant)} + {estimated_tokens} > {limit})",
            )
        self._next_reservation += 1
        self._open[self._next_reservation] = (tenant, estimated_tokens)
        return Decision(True, reservation=self._next_reservation)

    def release(self, reservation: int = 0, actual_tokens: int | None = None) -> None:
        """Free the slot, and settle the reservation against what it really cost.

        ``actual_tokens=None`` means the caller does not know - a generation that
        raised part-way, say - and the estimate stays charged, in ``estimated``
        rather than in ``settled``.

        ``reservation=0`` releases the oldest open one, which is what a caller that
        holds exactly one reservation means and what the previous no-argument
        signature did.
        """
        if not self._open:
            raise RuntimeError("released more generations than were admitted")
        if reservation == 0:
            reservation = next(iter(self._open))
        if reservation not in self._open:
            raise RuntimeError(f"reservation {reservation} is not open")
        tenant, held = self._open.pop(reservation)
        if actual_tokens is None:
            self._estimated[tenant] = self.estimated(tenant) + held
            return
        if actual_tokens < 0:
            raise ValueError("actual_tokens cannot be negative")
        self._settled[tenant] = self.settled(tenant) + actual_tokens
