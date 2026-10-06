"""Real routing instances with known optimal answers.

Six TSPLIB instances, each committed with its proven optimal tour: eil51,
berlin52, st70, pr76, kroA100 and ch150 — 51 to 150 stops.

That combination is what makes this product's claim testable rather than
rhetorical. "Do not let a model plan a route" is an assertion; *how much worse
than optimal* a plausible-looking route is, on real coordinates against a proven
answer, is a number.

Six rather than one for two reasons. The excess is not a constant — a circular
sweep is 54% worse than optimal at 51 stops and 181% worse at 150, so a single
instance cannot say whether the number grows with the fleet. And six independent
published optima are six independent checks on the EUC_2D rounding rule below;
one instance agreeing could be luck.

Distances follow TSPLIB's EUC_2D rule, which rounds to the nearest integer. Using
raw floats instead produces tour lengths that disagree with every published
figure by a few units, which looks like a bug in the solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"
INSTANCE = DATA / "berlin52.tsp"
OPTIMAL = DATA / "berlin52.opt.tour"

# Instance -> its published optimal tour length. These are the numbers TSPLIB
# publishes; `tour_length(optimal_tour())` must reproduce each one exactly.
PUBLISHED = {
    "eil51": 426,
    "berlin52": 7_542,
    "st70": 675,
    "pr76": 108_159,
    "kroA100": 21_282,
    "ch150": 6_528,
}


def instance(name: str) -> tuple[str, str]:
    """Paths to an instance and its optimal tour, by TSPLIB name."""
    if name not in PUBLISHED:
        raise InstanceMissingError(f"{name} is not one of {sorted(PUBLISHED)}")
    return str(DATA / f"{name}.tsp"), str(DATA / f"{name}.opt.tour")


class InstanceMissingError(FileNotFoundError):
    """The TSPLIB files are not on disk."""


@dataclass(frozen=True)
class City:
    id: int
    x: float
    y: float


def euc_2d(a: City, b: City) -> int:
    """TSPLIB's EUC_2D: Euclidean distance rounded to the nearest integer."""
    return int(round(math.hypot(a.x - b.x, a.y - b.y)))


@lru_cache(maxsize=16)
def cities(path: str | None = None) -> tuple[City, ...]:
    target = Path(path) if path else INSTANCE
    if not target.exists():
        raise InstanceMissingError(f"{target} is missing. Fetch it from TSPLIB.")
    out: list[City] = []
    reading = False
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("NODE_COORD_SECTION"):
            reading = True
            continue
        if line in {"EOF", ""} or line.startswith("DISPLAY"):
            if reading and line == "EOF":
                break
            continue
        if reading:
            parts = line.split()
            if len(parts) >= 3:
                out.append(City(int(parts[0]), float(parts[1]), float(parts[2])))
    if not out:
        raise InstanceMissingError(f"{target} has no NODE_COORD_SECTION")
    return tuple(out)


@lru_cache(maxsize=16)
def optimal_tour(path: str | None = None) -> tuple[int, ...]:
    """The proven optimal ordering, as city ids."""
    target = Path(path) if path else OPTIMAL
    if not target.exists():
        raise InstanceMissingError(f"{target} is missing. Fetch its TSPLIB optimum.")
    out: list[int] = []
    reading = False
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("TOUR_SECTION"):
            reading = True
            continue
        if not reading or not line:
            continue
        if line in {"-1", "EOF"}:
            break
        out.append(int(line))
    return tuple(out)


def matrix(path: str | None = None) -> dict:
    """A full distance matrix keyed by (id, id), in the product's own shape."""
    pts = cities(path)
    return {(str(a.id), str(b.id)): euc_2d(a, b) for a in pts for b in pts if a.id != b.id}


def tour_length(order: list[int], path: str | None = None) -> int:
    """Closed-tour length under EUC_2D."""
    pts = {c.id: c for c in cities(path)}
    if len(order) < 2:
        raise ValueError("a tour needs at least two stops")
    return sum(
        euc_2d(pts[order[i]], pts[order[(i + 1) % len(order)]]) for i in range(len(order))
    )


def nearest_neighbour(start: int = 1, path: str | None = None) -> list[int]:
    """The obvious greedy construction: always go to the closest unvisited stop."""
    pts = {c.id: c for c in cities(path)}
    unvisited = set(pts) - {start}
    order = [start]
    current = start
    while unvisited:
        nxt = min(unvisited, key=lambda i: euc_2d(pts[current], pts[i]))
        order.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    return order


def by_index(path: str | None = None) -> list[int]:
    """Visit the stops in the order they appear in the file.

    This is the shape of route a language model produces when asked to order
    stops it cannot compute distances over: it looks like a plan, it visits
    everything exactly once, and nothing about it is a route.
    """
    return [c.id for c in cities(path)]


def sweep(path: str | None = None) -> list[int]:
    """Order stops by angle around the centroid.

    A genuinely sensible-looking heuristic, and the kind of reasoning a model
    can actually do: "go round the city in a circle".
    """
    pts = cities(path)
    cx = sum(c.x for c in pts) / len(pts)
    cy = sum(c.y for c in pts) / len(pts)
    return [c.id for c in sorted(pts, key=lambda c: math.atan2(c.y - cy, c.x - cx))]


def excess(order: list[int], path: str | None = None) -> float:
    """How much longer than optimal, as a fraction."""
    best = tour_length(list(optimal_tour(path and str(OPTIMAL))), path)
    return tour_length(order, path) / best - 1
