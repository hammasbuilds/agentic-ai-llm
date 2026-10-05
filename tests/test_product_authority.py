"""Every product's write-authority table, checked rather than declared.

Nineteen of the twenty per-product tests asserted only

    agents.authority().level_for("nobody", "anything") is Level.NEVER

which is the platform's default and cannot fail for any table, including an empty one.
A table with no grants at all would have passed all nineteen.

And every one of the twenty READMEs says the table is *enforced*. It is not: nothing in
any product's runtime passes an agent identity, so the tables are a declaration of intent
and the platform supplies the check that nobody calls. That sentence is corrected in the
READMEs; this file is what makes the declaration worth having - a table that is wrong is
worse than no table, because it is read as a guarantee.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for src in sorted((ROOT / "products").glob("*/src")):
    sys.path.insert(0, str(src))

from agentplatform.authority import Level, NotAuthorisedError, Table  # noqa: E402

#: Product directory -> the package its agents live in.
PRODUCTS = {
    path.name: next(
        p.name for p in (path / "src").iterdir() if p.is_dir() and p.name != "__pycache__"
    )
    for path in sorted((ROOT / "products").glob("[0-9]*"))
    if (path / "src").is_dir()
}


def table_for(package: str) -> Table:
    return importlib.import_module(f"{package}.agents").authority()


def test_there_are_twenty_products_to_check():
    """A parametrised sweep over an empty mapping passes."""
    assert len(PRODUCTS) == 20, sorted(PRODUCTS)


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_the_table_grants_something_and_denies_everyone_else(product, package):
    """The grants are real, and an agent nobody named gets none of them."""
    table = table_for(package)
    grants = table._grants
    assert len(grants) >= 3, f"{product}: {len(grants)} grant(s)"

    for (agent, field), level in grants.items():
        assert isinstance(level, Level), (product, agent, field)
        # The field is open to the agent it was granted to...
        assert table.level_for(agent, field) is level, (product, agent, field)
        # ...and to nobody else.
        assert table.level_for("nobody-at-all", field) is Level.NEVER, (product, field)


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_a_grant_on_the_children_is_not_a_grant_on_the_parent(product, package):
    """ "patch.*" used to answer a question about bare "patch", because the prefix of a
    dotless name is itself. "May draft a patch" authorised writing the patch."""
    table = table_for(package)
    for agent, field in list(table._grants):
        if not field.endswith(".*"):
            continue
        parent = field[:-2]
        if (agent, parent) in table._grants:
            continue  # granted explicitly as well, which is a different statement
        assert table.level_for(agent, parent) is Level.NEVER, (product, agent, parent)


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_check_refuses_what_level_for_denies(product, package):
    """`check` is the raising form. The two must agree, or a caller that uses one is
    protected and a caller that uses the other is not."""
    table = table_for(package)
    agent = next(iter(table._grants))[0]
    with pytest.raises(NotAuthorisedError):
        table.check(agent, "a.field.nobody.granted")
