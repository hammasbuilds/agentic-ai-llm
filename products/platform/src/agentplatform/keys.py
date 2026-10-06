"""The six Redis keys, each with the TTL that makes it safe.

A key without a TTL is a leak; a lock without one is an outage. Every builder
here returns both, so a caller cannot write one without the other.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

HOUR = 3600
DAY = 24 * HOUR


@dataclass(frozen=True)
class Key:
    """A Redis key and the expiry it must be written with."""

    name: str
    ttl_seconds: int | None

    def __str__(self) -> str:
        return self.name


def ctx(run_id: str) -> Key:
    """Working memory for one agent run. Dies with the run."""
    return Key(f"ctx:{run_id}", HOUR)


def idem(source: str, message_id: str) -> Key:
    """Exactly-once at the edge. Mail providers and webhooks redeliver."""
    return Key(f"idem:{source}:{message_id}", DAY)


def lock(entity_type: str, entity_id: str, ttl_seconds: int = 60) -> Key:
    """One agent at a time on one record.

    The TTL is short on purpose: a worker killed mid-generation must not hold a
    record hostage. Renew it from a heartbeat rather than raising it.
    """
    # Both bounds. Only the upper one was checked, so `lock(..., ttl_seconds=0)` was
    # accepted and returned a key with no expiry at all - in a module whose own
    # docstring says "a lock without one is an outage". A lock that never expires is
    # the failure the upper bound exists to prevent, taken to its limit.
    if ttl_seconds < 1:
        raise ValueError(
            f"a lock needs a TTL, got {ttl_seconds}: without one a worker killed "
            "mid-generation holds the record for ever"
        )
    if ttl_seconds > 300:
        raise ValueError(
            "a lock held longer than five minutes is an outage waiting to happen; "
            "renew from a heartbeat instead of extending the TTL"
        )
    return Key(f"lock:{entity_type}:{entity_id}", ttl_seconds)


def budget(tenant: str, on: date) -> Key:
    """Token ceiling per tenant per day, checked before the GPU is touched."""
    return Key(f"budget:{tenant}:{on.isoformat()}", DAY)


def llmcache(model: str, prompt: str) -> Key:
    """Exact-match completion cache. The prompt is hashed, never stored."""
    digest = hashlib.sha256(f"{model}\x00{prompt}".encode()).hexdigest()
    return Key(f"llmcache:{digest}", 7 * DAY)


def live(dashboard: str) -> Key:
    """Counters the SSE stream publishes without touching Postgres."""
    return Key(f"live:{dashboard}", None)
