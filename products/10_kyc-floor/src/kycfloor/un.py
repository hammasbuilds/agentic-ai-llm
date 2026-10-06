"""The UN Security Council consolidated list — a second, independent ground truth.

OFAC's SDN and ALT exports gave this product 8,650 labelled (primary, alias)
pairs, and every headline number came off that one list. A matching rule tuned
on one authority's transliteration habits is a rule about that authority, so the
UN's consolidated list is read here as a check: a different body, a different
listing process, a different mix of regions, and the same kind of label.

Two structural differences matter.

The UN writes names in given-name order across FIRST_NAME..FOURTH_NAME, where
OFAC writes "SURNAME, Given". Since `domain.normalise` reduces a name to an
unordered token set, that difference costs nothing — which is itself worth
having checked rather than assumed.

The UN grades its aliases. Each carries a QUALITY of "Good" or "Low", where
"Low" means the UN itself is unsure the alias belongs to the person. OFAC
publishes no equivalent, so this list can answer a question OFAC cannot: whether
a matcher's misses are concentrated in the labels that were weakest to begin
with.

`un_consolidated.xml` is fetched rather than committed — see
`scripts/fetch_data.sh`. Every test that reads it skips cleanly when it is
absent.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"
LIST = DATA / "un_consolidated.xml"

NAME_PARTS = ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")

GOOD = "Good"
LOW = "Low"


class ListMissingError(FileNotFoundError):
    """The UN consolidated list is not on disk."""


@dataclass(frozen=True)
class Listed:
    data_id: str
    primary: str
    aliases: tuple[tuple[str, str], ...]  # (alias, quality)

    @property
    def good_aliases(self) -> tuple[str, ...]:
        return tuple(a for a, q in self.aliases if q == GOOD)


@lru_cache(maxsize=1)
def individuals(path: str | None = None) -> tuple[Listed, ...]:
    """Every listed individual, with their graded aliases."""
    target = Path(path) if path else LIST
    if not target.exists():
        raise ListMissingError(
            f"{target} is missing. Fetch the UN consolidated list; see scripts/fetch_data.sh."
        )
    root = ET.parse(target).getroot()
    block = root.find("INDIVIDUALS")
    if block is None:
        return ()

    out: list[Listed] = []
    for person in block:
        parts = [(person.findtext(tag) or "").strip() for tag in NAME_PARTS]
        primary = " ".join(p for p in parts if p)
        if not primary:
            continue
        aliases = []
        for node in person.findall("INDIVIDUAL_ALIAS"):
            name = (node.findtext("ALIAS_NAME") or "").strip()
            quality = (node.findtext("QUALITY") or "").strip()
            if name:
                aliases.append((name, quality))
        out.append(
            Listed(
                data_id=(person.findtext("DATAID") or "").strip(),
                primary=primary,
                aliases=tuple(aliases),
            )
        )
    return tuple(out)


def labelled_pairs(
    path: str | None = None, quality: str | None = None
) -> list[tuple[str, str]]:
    """(primary, alias) pairs the UN has declared to be one person.

    ``quality`` filters to "Good" or "Low" aliases; None takes both.
    """
    return [
        (person.primary, alias)
        for person in individuals(path)
        for alias, grade in person.aliases
        if quality is None or grade == quality
    ]
