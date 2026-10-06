"""A bounded walk that carries its provenance.

An answer naming its entities but not the documents that connected them cannot
be checked, which makes it indistinguishable from a fluent guess.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    source: str  # the document id that stated this relation

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError(
                f"edge {self.src}-[{self.rel}]->{self.dst} has no source document; "
                "an inferred edge is not an edge"
            )


@dataclass(frozen=True)
class Path:
    nodes: tuple[str, ...]
    edges: tuple[Edge, ...]

    @property
    def hops(self) -> int:
        return len(self.edges)

    @property
    def sources(self) -> tuple[str, ...]:
        """Every document this path depends on. The citation list."""
        seen: list[str] = []
        for edge in self.edges:
            if edge.source not in seen:
                seen.append(edge.source)
        return tuple(seen)


def _adjacency(edges: list[Edge]) -> dict[str, list[Edge]]:
    out: dict[str, list[Edge]] = {}
    for edge in edges:
        out.setdefault(edge.src, []).append(edge)
    return out


def traverse(edges: list[Edge], start: str, max_hops: int = 2) -> list[Path]:
    """Every path out of ``start`` up to ``max_hops``, breadth first.

    Cycle-safe by construction: a node already on the current path is not
    revisited, so ``A relates to B`` and ``B relates to A`` terminates.
    """
    if max_hops < 1:
        raise ValueError("a traversal of zero hops is a lookup, not a walk")
    adjacency = _adjacency(edges)
    found: list[Path] = []
    queue: deque[Path] = deque([Path((start,), ())])
    while queue:
        path = queue.popleft()
        if path.hops >= max_hops:
            continue
        for edge in adjacency.get(path.nodes[-1], []):
            if edge.dst in path.nodes:
                continue
            extended = Path(path.nodes + (edge.dst,), path.edges + (edge,))
            found.append(extended)
            queue.append(extended)
    return found


def reachable(edges: list[Edge], start: str, max_hops: int = 2) -> set[str]:
    return {p.nodes[-1] for p in traverse(edges, start, max_hops)}


def shortest(edges: list[Edge], start: str, end: str, max_hops: int = 4) -> Path | None:
    """The shortest evidenced connection, or None. Never a guess."""
    for path in traverse(edges, start, max_hops):
        if path.nodes[-1] == end:
            return path
    return None


def contradictions(edges: list[Edge]) -> list[tuple[Edge, Edge]]:
    """Pairs of edges asserting different objects for one (subject, relation).

    Reported, never resolved: two documents disagreeing is the finding, and
    picking one is a clinician's call.
    """
    grouped: dict[tuple[str, str], list[Edge]] = {}
    for edge in edges:
        grouped.setdefault((edge.src, edge.rel), []).append(edge)
    out: list[tuple[Edge, Edge]] = []
    for group in grouped.values():
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                if first.dst != second.dst and first.source != second.source:
                    out.append((first, second))
    return out
