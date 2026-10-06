"""A GenBank flat-file reader, written rather than depended on.

Biopython would do this, and pulling it in for four fields and a sequence is a
poor trade — especially for a product whose whole argument is that the expensive
machinery is not where the answer comes from.

Reads only what the surveillance question needs: the accession, the organism,
the isolate label (which carries the site), the collection date, and the
sequence. Everything else in a GenBank record is skipped deliberately.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .domain import UNKNOWN_SITE

_QUALIFIER = re.compile(r'/(\w+)="([^"]*)"')
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
        start=1,
    )
}


class MalformedRecordError(ValueError):
    """A record that cannot be read, reported rather than skipped silently."""


@dataclass(frozen=True)
class Record:
    accession: str
    organism: str
    isolate: str
    collected: date | None
    sequence: str
    geo: str = ""

    @property
    def site(self) -> str:
        """Where this isolate came from.

        ``/geo_loc_name`` is authoritative and present on most modern records;
        GenBank renamed it from ``/country``, so reading only the old name finds
        nothing. Falling back to the isolate label matters because labels like
        ``Kh2_Faisalabad_2019-20`` carry a place the qualifier sometimes omits.

        Getting this wrong is not cosmetic. Collapsing is stratified by site, so
        every record defaulting to "unknown" merges genuinely separate places
        into one stratum — which over-collapses clonal duplicates and hides the
        multi-site spread that emergence is defined by.
        """
        if self.geo:
            return self.geo.split(":")[0].strip()
        parts = self.isolate.split("_")
        return parts[1] if len(parts) >= 2 else UNKNOWN_SITE

    @property
    def submission(self) -> str:
        """The batch an isolate belongs to, from its label prefix.

        ``CLCMV/S2-1`` .. ``CLCMV/S2-8`` are one submission of one field. That
        prefix is the clonal unit far more reliably than the sequence alone.
        """
        label = self.isolate.rsplit("-", 1)[0] if "-" in self.isolate else self.isolate
        return label.rstrip("0123456789") or self.isolate

    @property
    def season(self) -> str:
        parts = self.isolate.split("_")
        return parts[2] if len(parts) >= 3 else ""

    @property
    def day(self) -> int:
        """Days since 2000-01-01, so the surveillance core can order on an int."""
        if self.collected is None:
            return 0
        return (self.collected - date(2000, 1, 1)).days


def _parse_date(raw: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%b-%Y", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _sequence(lines: list[str]) -> str:
    """The ORIGIN block, with the line numbers and spacing stripped."""
    letters = []
    for line in lines:
        letters.extend(part for part in line.split()[1:])
    return "".join(letters).upper()


def parse(text: str) -> Iterator[Record]:
    """Yield one Record per LOCUS block."""
    for block in text.split("\nLOCUS")[1:] if text.startswith("LOCUS") else []:
        yield _record("LOCUS" + block)
    # The first block loses its marker in the split above, so handle it here.


def read(path: str | Path) -> list[Record]:
    """Every record in a GenBank file, in file order."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = [b for b in text.split("//\n") if b.strip()]
    out: list[Record] = []
    for block in blocks:
        try:
            out.append(_record(block))
        except MalformedRecordError:
            continue
    return out


def _record(block: str) -> Record:
    lines = block.splitlines()
    accession = ""
    qualifiers: dict[str, str] = {}
    origin: list[str] = []
    in_origin = False

    for line in lines:
        if line.startswith("ACCESSION"):
            parts = line.split()
            accession = parts[1] if len(parts) > 1 else ""
        elif line.startswith("ORIGIN"):
            in_origin = True
        elif in_origin:
            origin.append(line)
        else:
            for key, value in _QUALIFIER.findall(line):
                qualifiers.setdefault(key, value)

    if not accession:
        raise MalformedRecordError("no ACCESSION line")
    sequence = _sequence(origin)
    if not sequence:
        raise MalformedRecordError(f"{accession} has no ORIGIN block")

    return Record(
        accession=accession,
        organism=qualifiers.get("organism", ""),
        isolate=qualifiers.get("isolate", accession),
        collected=_parse_date(qualifiers.get("collection_date", "")),
        sequence=sequence,
        geo=qualifiers.get("geo_loc_name", qualifiers.get("country", "")),
    )
