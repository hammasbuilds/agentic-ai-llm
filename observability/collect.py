"""JSON Lines in, panels out. Pure functions, so a panel is testable without a server.

The unit here is a **job**, not a tool call: an app runs a measurement, it takes a while,
and it ends in `done` or `error`. The panels follow from that.

The one worth explaining is **transport**. This repository's README is careful about it —
Kafka, Redis, Postgres and Ollama adapters all ship and no product binds one, so every
`runtime()` constructs the in-memory bus and store. A console showing `inline: 100%` is
therefore reporting the truth rather than a misconfiguration, and the panel says so, so
that nobody reads it as something to go and fix. The moment somebody starts `worker.py`,
that figure changes on its own, which is the point of showing it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

#: Below this, a percentile is reported with the count beside it rather than alone.
THIN = 20


def read(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Every readable event, oldest first. A half-written last line is skipped."""
    events: list[dict[str, Any]] = []
    for candidate in (path.with_suffix(path.suffix + ".1"), path):
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    events.sort(key=lambda e: e.get("at") or 0)
    return events[-limit:] if limit else events


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def summarise(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Every panel the console draws."""
    seconds = [float(e.get("seconds") or 0) for e in events]
    outcomes = Counter(str(e.get("outcome") or "unknown") for e in events)
    transports = Counter(str(e.get("transport") or "unknown") for e in events)
    errors = Counter(str(e["error"]) for e in events if e.get("error"))

    by_app: dict[str, dict[str, Any]] = {}
    for event in events:
        app = str(event.get("app") or "unknown")
        row = by_app.setdefault(
            app, {"app": app, "runs": 0, "done": 0, "error": 0, "items": 0, "seconds": []}
        )
        row["runs"] += 1
        if str(event.get("outcome")) == "done":
            row["done"] += 1
        else:
            row["error"] += 1
        items = event.get("items")
        if isinstance(items, (int, float)) and not isinstance(items, bool):
            row["items"] += int(items)
        row["seconds"].append(float(event.get("seconds") or 0))

    apps = []
    for row in by_app.values():
        times = row.pop("seconds")
        row["p50"] = round(_percentile(times, 0.50), 2)
        row["p95"] = round(_percentile(times, 0.95), 2)
        row["max"] = round(max(times), 2) if times else 0.0
        row["total"] = round(sum(times), 1)
        row["thin"] = len(times) < THIN
        # `None` rather than 0.0 for an app that has never failed AND never run: the two
        # read the same on a dashboard and are not the same fact.
        row["failure_rate"] = round(row["error"] / row["runs"], 3) if row["runs"] else None
        apps.append(row)
    apps.sort(key=lambda r: (-r["runs"], r["app"]))

    done = outcomes.get("done", 0)
    failed = sum(n for name, n in outcomes.items() if name != "done")

    return {
        "runs": len(events),
        "first": min((e.get("at") or 0) for e in events) if events else None,
        "last": max((e.get("at") or 0) for e in events) if events else None,
        "done": done,
        "failed": failed,
        "failure_rate": round(failed / len(events), 3) if events else None,
        "outcomes": dict(outcomes.most_common()),
        "transports": dict(transports.most_common()),
        "errors": dict(errors.most_common()),
        "p50": round(_percentile(seconds, 0.50), 2),
        "p95": round(_percentile(seconds, 0.95), 2),
        "max": round(max(seconds), 2) if seconds else 0.0,
        "compute_seconds": round(sum(seconds), 1),
        "thin": len(seconds) < THIN,
        "thin_at": THIN,
        "apps": apps,
        "recent": [
            {
                k: v
                for k, v in e.items()
                if k in ("at", "app", "outcome", "seconds", "transport", "items", "error")
            }
            for e in events[-25:][::-1]
        ],
    }
