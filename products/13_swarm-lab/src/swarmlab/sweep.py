"""Running N agents against real infrastructure and counting what they collide over.

The coordination failures this product measures — duplicate tool calls,
conflicting writes — are structural. They come from several workers sharing a
queue and a store, not from what any of them is thinking, so they can be
measured exactly without a model in the loop. That is a feature: it removes the
largest source of variance from a study whose whole point is the effect of N.

Runs against the real Redis and the real Kafka when they are up, and against the
in-memory ports otherwise. The interesting number — how often two agents reach
for the same entity — is the same measurement either way, and with real Redis
the lock is a real `SET NX`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from agentplatform import keys
from agentplatform.ports import InMemoryCache

from .domain import ToolCall, Write, conflicting_writes, duplicate_calls


@dataclass
class Trial:
    n_agents: int
    topology: str
    entities: int
    calls: list = field(default_factory=list)
    writes: list = field(default_factory=list)
    lock_contentions: int = 0
    wall_seconds: float = 0.0

    @property
    def duplicates(self) -> int:
        return duplicate_calls(self.calls)

    @property
    def conflicts(self) -> int:
        return len(conflicting_writes(self.writes))

    @property
    def duplicate_rate(self) -> float:
        return self.duplicates / len(self.calls) if self.calls else 0.0


def _redis():
    """Real Redis if it answers, otherwise the in-memory cache.

    Every trial records which it got, in `Trial.real_redis`, and :func:`backend`
    summarises it for the results table - because a silent fallback behind a claim
    of "the real Redis" is the claim being wrong rather than the fallback being bad.
    """
    try:
        from agentplatform.adapters import RedisCache

        cache = RedisCache()
        if cache.ping():
            return cache, True
    except Exception:  # noqa: BLE001 - absence is not an incident
        pass
    return InMemoryCache(), False


def run_trial(
    n_agents: int,
    *,
    entities: int = 40,
    topology: str = "flat",
    use_lock: bool = False,
    seed: int = 0,
) -> Trial:
    """N agents work through a shared entity list, with or without a lock.

    Without a lock every agent picks work independently, which is how a flat
    swarm without shared state behaves and is exactly where duplication comes
    from. With the lock, an agent claims an entity first and skips it if someone
    else holds it.
    """
    if n_agents < 1:
        raise ValueError("a trial needs at least one agent")

    cache, real = _redis()
    run_id = f"sweep{seed}-{n_agents}-{int(time.time() * 1000)}"
    trial = Trial(n_agents=n_agents, topology=topology, entities=entities)

    lock = threading.Lock()
    seq = [0]
    started = time.monotonic()

    def agent(index: int) -> None:
        # In a hierarchy a supervisor partitions the work; in a flat swarm every
        # agent sees the whole list. That difference is the topology.
        mine = (
            range(index, entities, n_agents) if topology == "hierarchical" else range(entities)
        )
        for entity in mine:
            key = keys.lock("entity", f"{run_id}:{entity}")
            if use_lock and not cache.add(key.name, str(index), key.ttl_seconds):
                with lock:
                    trial.lock_contentions += 1
                continue
            with lock:
                seq[0] += 1
                order = seq[0]
                trial.calls.append(ToolCall(f"a{index}", "fetch", {"entity": entity}, order))
                trial.writes.append(
                    Write(f"a{index}", f"e{entity}", "status", f"done-by-a{index}", order)
                )

    threads = [threading.Thread(target=agent, args=(i,)) for i in range(n_agents)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    trial.wall_seconds = time.monotonic() - started
    trial.real_redis = real  # type: ignore[attr-defined]
    return trial


FIBONACCI = (1, 2, 3, 5, 8, 13, 21)


def sweep(
    sizes=FIBONACCI, *, repeats: int = 3, entities: int = 40, **kw
) -> dict[int, list[Trial]]:
    """One cell per N, repeated. Three repeats minimum; one run is not a rate."""
    if repeats < 3:
        raise ValueError("a cell needs at least three repeats to be a rate")
    return {
        n: [run_trial(n, entities=entities, seed=r, **kw) for r in range(repeats)]
        for n in sizes
    }


def backend(cells: dict[int, list[Trial]]) -> str:
    """Which cache the sweep actually ran against, as a line to print.

    The README said "measured by running N workers against the real Redis" without
    qualification, and `_redis()` falls back to the in-memory cache whenever Redis
    does not answer. On a machine with no Redis up, every table in that README was
    produced by the fallback and said otherwise. The numbers happen to be the same
    either way - the duplication is structural - but which one ran is not a detail a
    reader should have to assume.
    """
    trials = [t for cell in cells.values() for t in cell]
    real = sum(1 for t in trials if getattr(t, "real_redis", False))
    if real == len(trials):
        return f"all {len(trials)} trials against a real Redis (`SET NX`)"
    if real == 0:
        return f"all {len(trials)} trials against the in-memory cache; no Redis answered"
    return f"{real} of {len(trials)} trials against a real Redis, the rest in-memory"
