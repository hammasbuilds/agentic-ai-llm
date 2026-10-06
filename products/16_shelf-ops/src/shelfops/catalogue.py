"""Real products with real price distributions.

`products/data/prices.csv` is derived once from UCI Online Retail II by
`scripts/make_prices.py`: 4,502 products, each with the modal, minimum, maximum
and median price it actually transacted at.

The distribution is the point. A catalogue does not have "a price" — the same
product sold at many prices, and the spread is wide: the median product's range
is larger than its own modal price. A repricing agent is moving inside that
distribution, and the lowest price a product ever sold at is the most defensible
floor available, because the business demonstrably accepted it at least once.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data"
CATALOGUE = DATA / "prices.csv"


class CatalogueMissingError(FileNotFoundError):
    """The price table is not on disk. Run scripts/make_prices.py."""


@dataclass(frozen=True)
class Product:
    code: str
    description: str
    sales: int
    units: int
    modal: int  # minor units
    low: int
    high: int
    median: int

    @property
    def dispersion(self) -> float:
        """Observed range as a multiple of the modal price."""
        return (self.high - self.low) / self.modal if self.modal else 0.0

    @property
    def ever_discounted(self) -> bool:
        return self.low < self.modal

    @property
    def floor(self) -> int:
        """The lowest price this product ever actually sold at.

        Used as the price floor because it is evidence rather than an
        assumption: the business accepted it, at least once, for this product.
        """
        return self.low


@lru_cache(maxsize=1)
def load(path: str | None = None) -> tuple[Product, ...]:
    target = Path(path) if path else CATALOGUE
    if not target.exists():
        raise CatalogueMissingError(
            f"{target} is missing. Build it with: python scripts/make_prices.py"
        )
    with target.open(encoding="utf-8", newline="") as fh:
        return tuple(
            Product(
                code=r["code"],
                description=r["description"],
                sales=int(r["sales"]),
                units=int(r["units"]),
                modal=int(r["modal"]),
                low=int(r["min"]),
                high=int(r["max"]),
                median=int(r["median"]),
            )
            for r in csv.DictReader(fh)
            if int(r["modal"]) > 0
        )


def dispersion(path: str | None = None) -> dict:
    products = load(path)
    spread = sorted(p.dispersion for p in products)
    return {
        "products": len(products),
        "median": statistics.median(spread),
        "p90": spread[int(0.9 * len(spread))],
        "ever_discounted": sum(1 for p in products if p.ever_discounted) / len(products),
    }


@dataclass(frozen=True)
class Breach:
    """What each pricing policy does against the observed floor."""

    products: int
    single_authority: int
    compounded: int
    only_compounded: int

    @property
    def attributable(self) -> float:
        """Share of the catalogue broken by compounding and nothing else."""
        return self.only_compounded / self.products if self.products else 0.0


def breaches(proposals, path: str | None = None) -> Breach:
    """Compare one price authority against two agents each applying a discount."""
    from .domain import compounded as compound_all
    from .domain import decide

    products = load(path)
    single = both = only = 0
    for product in products:
        chosen = decide(product.modal, list(proposals), floor=1).value
        stacked = compound_all(product.modal, list(proposals))
        if chosen < product.floor:
            single += 1
        if stacked < product.floor:
            both += 1
            if chosen >= product.floor:
                only += 1
    return Breach(len(products), single, both, only)
