"""Reading real logs, and turning lines into templates.

`products/data/*_2k.log` are Loghub's published samples — real production logs
from five different systems: HDFS, BlueGene/L, an HPC cluster, OpenStack and
ZooKeeper. Different formats, different eras, different failure modes, which is
the point: a templater tuned to one log shape is a templater that works on one
log shape.

Templating is the Drain idea without the tree: replace the parts of a line that
vary between occurrences, keep the parts that identify the fault.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"

# Ordered. Each pattern removes something that varies per occurrence while the
# fault stays the same. Getting the order wrong (hex before block ids, say)
# produces templates that look right and collapse the wrong things together.
_MASKS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\bblk_-?\d+\b"), "<blk>"),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<uuid>",
    ),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hex>"),
    (re.compile(r"/[\w./\-]+"), "<path>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\b"), "<ts>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<num>"),
)

# All sixteen Loghub systems, not the five that happened to be downloaded
# first. The product's finding is the SPREAD of the compression ratio, and a
# spread taken from five points says very little about its ends.
SYSTEMS = (
    "android",
    "apache",
    "bgl",
    "hadoop",
    "hdfs",
    "healthapp",
    "hpc",
    "linux",
    "mac",
    "openssh",
    "openstack",
    "proxifier",
    "spark",
    "thunderbird",
    "windows",
    "zookeeper",
)


class LogsMissingError(FileNotFoundError):
    """The Loghub samples are not on disk."""


@dataclass(frozen=True)
class Line:
    system: str
    n: int
    raw: str

    @property
    def template(self) -> str:
        return template(self.raw)

    @property
    def level(self) -> str:
        for level in ("FATAL", "ERROR", "WARN", "INFO", "DEBUG"):
            if level in self.raw:
                return level
        return "INFO"


def template(line: str) -> str:
    """One log line reduced to its shape."""
    out = line.strip()
    for pattern, mask in _MASKS:
        out = pattern.sub(mask, out)
    return " ".join(out.split())


@lru_cache(maxsize=1)
def read(root: str | None = None) -> tuple[Line, ...]:
    """Every line of every Loghub sample on disk."""
    base = Path(root) if root else DATA
    out: list[Line] = []
    for system in SYSTEMS:
        path = base / f"{system}_2k.log"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, raw in enumerate(text.splitlines()):
            if raw.strip():
                out.append(Line(system, n, raw))
    if not out:
        raise LogsMissingError(f"no *_2k.log under {base}")
    return tuple(out)


@dataclass(frozen=True)
class Compression:
    """What templating did to a corpus."""

    lines: int
    distinct_raw: int
    distinct_templates: int
    raw_seen_once: int
    templates_seen_once: int

    @property
    def ratio(self) -> float:
        return self.distinct_raw / self.distinct_templates

    @property
    def messages_lost(self) -> int:
        return self.distinct_raw - self.distinct_templates

    @property
    def rare_lost(self) -> int:
        """Messages seen exactly once that no longer exist as their own template.

        The number that matters. An incident is made of the line that appeared
        once, and compression eats those first.
        """
        return self.raw_seen_once - self.templates_seen_once


def compression(lines: list[Line] | tuple[Line, ...]) -> Compression:
    raws = Counter(line.raw.strip() for line in lines)
    templates = Counter(line.template for line in lines)
    return Compression(
        lines=len(lines),
        distinct_raw=len(raws),
        distinct_templates=len(templates),
        raw_seen_once=sum(1 for c in raws.values() if c == 1),
        templates_seen_once=sum(1 for c in templates.values() if c == 1),
    )
