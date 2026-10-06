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


# -- claims about the UI and the route surface ----------------------------


def test_no_product_readme_describes_a_frontend_as_though_it_were_built():
    """All twenty named a framework. None of them exists.

    An independent review looked for a single `package.json`, `.tsx`, `.svelte`,
    `.vue`, `.dart` or `.astro` file across all twenty products and found none — the
    lines read `**UI:** Angular 19 — pipeline board, …` and sat flat beside the real
    topic and schema tables with nothing marking them as intent. What ships is one
    232-line plain-JavaScript console.
    """
    import re

    readmes = sorted(ROOT.glob("products/[0-9][0-9]_*/README.md"))
    assert len(readmes) == 20, [p.parent.name for p in readmes]

    for readme in readmes:
        text = readme.read_text(encoding="utf-8")
        bare = re.search(r"^\*\*UI:\*\*", text, re.MULTILINE)
        assert not bare, f"{readme.parent.name} claims a UI without saying it is not built"
        assert "**UI, designed and not built**" in text, readme.parent.name


def test_there_really_is_no_frontend_in_the_tree():
    """The claim the line above makes, checked rather than taken on trust."""
    patterns = ("*.tsx", "*.jsx", "*.svelte", "*.vue", "*.dart", "*.astro", "package.json")
    found = [
        str(path.relative_to(ROOT))
        for pattern in patterns
        for path in (ROOT / "products").rglob(pattern)
        if ".venv" not in path.parts and "node_modules" not in path.parts
    ]
    assert found == [], f"a frontend appeared; the README lines need updating: {found}"


def test_the_index_counts_the_routes_the_api_registers():
    """It said "Four routes", counting the four user-facing *actions*. There are ten."""
    import re

    source = (ROOT / "products" / "platform" / "src" / "agentplatform" / "api.py").read_text(
        encoding="utf-8"
    )
    decorated = source.count("@app.")

    index = (ROOT / "products" / "README.md").read_text(encoding="utf-8")
    stated = re.search(r"it\. (\w+)\nroutes serving", index)
    assert stated, "the index no longer states a route count"

    words = {"Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10}
    assert words[stated.group(1)] == decorated, (
        f"the index says {stated.group(1)} routes; api.py declares {decorated}"
    )
    assert decorated == 10, "the index and this assertion must move together"
