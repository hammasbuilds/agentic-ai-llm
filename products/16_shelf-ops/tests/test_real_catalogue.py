"""shelf-ops against 4,502 real products.

`products/data/prices.csv` is derived once from UCI Online Retail II by
`scripts/make_prices.py`. Every figure asserted here was produced by running
this code over that file.
"""

import pytest

from shelfops.catalogue import CATALOGUE, breaches, dispersion, load
from shelfops.domain import PROMOTION, REPRICE, Proposal

pytestmark = pytest.mark.skipif(not CATALOGUE.exists(), reason="price table not built")

TWO_AGENTS = [
    Proposal("repricer", REPRICE, 10.0),
    Proposal("promotions", PROMOTION, 15.0),
]


@pytest.fixture(scope="module")
def products():
    return load()


def test_the_catalogue_loads(products):
    assert len(products) == 4_501
    assert all(p.modal > 0 for p in products)


def test_a_product_does_not_have_a_price_it_has_a_distribution():
    stats = dispersion()
    # The median product's observed range is wider than its own modal price.
    assert stats["median"] == pytest.approx(1.29, abs=0.05)
    assert stats["p90"] > 2.5


def test_most_products_have_sold_below_their_usual_price(products):
    assert dispersion()["ever_discounted"] == pytest.approx(0.787, abs=0.02)


def test_compounding_breaks_one_product_in_five(products):
    # THE FINDING. Two agents, each applying a discount that is individually
    # within policy, push 909 products below the lowest price that product has
    # ever actually sold at. One price authority applying the deeper of the two
    # does not.
    result = breaches(TWO_AGENTS)
    assert result.products == 4_501
    assert result.single_authority == 1_883
    assert result.compounded == 2_792
    assert result.only_compounded == 909
    assert result.attributable == pytest.approx(0.202, abs=0.01)


def test_the_single_authority_is_strictly_safer(products):
    result = breaches(TWO_AGENTS)
    assert result.compounded > result.single_authority
    assert result.only_compounded == result.compounded - result.single_authority


def test_the_floor_is_evidence_not_an_assumption(products):
    # The lowest price a product ever transacted at is a price the business
    # accepted. No cost figure is invented anywhere in this measurement.
    sample = products[0]
    assert sample.floor == sample.low
    assert sample.low <= sample.median <= sample.high


def test_a_shallower_pair_of_discounts_does_less_damage():
    gentle = [
        Proposal("repricer", REPRICE, 3.0),
        Proposal("promotions", PROMOTION, 5.0),
    ]
    assert breaches(gentle).only_compounded < breaches(TWO_AGENTS).only_compounded


def test_one_agent_alone_cannot_compound():
    solo = [Proposal("repricer", REPRICE, 15.0)]
    result = breaches(solo)
    assert result.only_compounded == 0


def test_a_missing_catalogue_is_reported_rather_than_faked():
    from shelfops.catalogue import CatalogueMissingError

    with pytest.raises(CatalogueMissingError):
        load(str(CATALOGUE.parent / "nope.csv"))


# -- the branch that reads the catalogue, not the catalogue itself -------------


def test_the_history_is_this_products_own_prices():
    """`_history` finds a product by code and was never called with a real one.

    `p.code == code` is the lookup, and mutating it to `!=` returns the FIRST product
    that is not the one asked for - so the pricing agent prices a shoe from a lamp's
    observed range. The whole suite stayed green, including this file, which tested the
    catalogue reader underneath it.
    """
    from shelfops.agents import _catalogue, _history

    catalogue = _catalogue()
    assert len(catalogue) > 100, len(catalogue)

    for product in (catalogue[0], catalogue[len(catalogue) // 2], catalogue[-1]):
        history = _history({"sku": product.code})
        assert history == [
            f"modal={product.modal}",
            f"min={product.low}",
            f"max={product.high}",
            f"sales={product.sales}",
        ], (product.code, history)


def test_a_sku_that_is_not_in_the_catalogue_returns_nothing():
    """Not another product's prices, and not a crash."""
    from shelfops.agents import _history

    assert _history({"sku": "no-such-sku"}) == []
    assert _history({}) == []
    assert _history({"sku": None}) == []


def test_two_different_skus_do_not_share_a_history():
    """The assertion the `==` mutation fails on: a wrong lookup returns the same rows
    for every code."""
    from shelfops.agents import _catalogue, _history

    catalogue = _catalogue()
    first = catalogue[0]
    shape = (first.modal, first.low, first.high, first.sales)
    second = next(p for p in catalogue if (p.modal, p.low, p.high, p.sales) != shape)
    assert _history({"sku": first.code}) != _history({"sku": second.code})
