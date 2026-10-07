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
import re
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


# -- what the platform declares and the products do not use ---------------


def _product_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for folder in sorted(ROOT.glob("products/[0-9][0-9]_*"))
        for path in folder.rglob("*.py")
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    )


def test_no_product_binds_a_real_adapter_on_its_serving_path():
    """Compose brings up Postgres, Redis and Kafka that nothing dials.

    Every `runtime()` constructs `InMemoryBus()` and `InMemoryStore()`, including the
    path `main()` serves from, and the index's opening line sells "an operator console
    over a real API, over a real event bus, over a real store". That describes the
    ports, not the wiring. The index says so now; this asserts it stays true or the
    index changes with it.
    """
    import re

    sources = _product_sources()
    constructed = re.findall(r"\b(KafkaBus|PostgresStore|RedisCache)\(", sources)
    assert len(constructed) == 1, f"{len(constructed)} real-adapter constructions: {constructed}"

    index = (ROOT / "products" / "README.md").read_text(encoding="utf-8")
    assert "**No product binds them.**" in index


@pytest.mark.parametrize("builder", ["ctx", "idem", "budget", "live"])
def test_the_key_builders_the_index_calls_unused_have_no_callers(builder):
    """Four of six. The module docstring argues for each of them."""
    import re

    sources = _product_sources() + "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "apps").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert not re.search(rf"keys\.{builder}\(", sources), (
        f"keys.{builder} has a caller now; the index table needs updating"
    )


def test_the_one_key_builder_with_a_real_caller_still_has_one():
    """So the table is not just a list of everything.

    `lock` is the only one of the six called from a product or an app. `llmcache` is
    called from `llm.Cached`, which no product constructs - so it is reachable in the
    platform and unused in practice, which is a third state the first version of this
    test had no name for and asserted away.
    """
    import re

    sources = _product_sources() + "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "apps").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert re.search(r"keys\.lock\(", sources), "keys.lock lost its caller"

    platform = (ROOT / "products" / "platform" / "src" / "agentplatform" / "llm.py").read_text(
        encoding="utf-8"
    )
    assert "keys.llmcache(" in platform, "llmcache's only caller is llm.Cached"
    assert not re.search(r"keys\.llmcache\(", sources), (
        "llmcache now has a product caller; the index table needs updating"
    )


def test_the_corroboration_gate_has_never_been_able_to_fire():
    """`gate.py` calls it "the only one most systems check" and `min_sources` is 1.

    Reachable - revenue-desk passes `state.get("min_sources", 1)` - and nothing in any
    product or test sets that key above 1, so the check has never run.
    """
    import ast

    # Read as code, not as text. The first version scanned source LINES, so it flagged
    # the sentence in `revenue/agents.py` explaining why `min_sources` is read from the
    # state - the fifth time a check in this repository has failed on its own prose.
    raised: list[str] = []
    for src in sorted((ROOT / "products").glob("[0-9]*/src")):
        for path in sorted(src.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # `min_sources=<something>` passed to a call, or a literal assignment.
                if isinstance(node, ast.keyword) and node.arg == "min_sources":
                    # `state.get("min_sources", 1)` is the reachable-but-unused form.
                    if isinstance(node.value, ast.Call):
                        continue
                    raised.append(f"{path.relative_to(ROOT).as_posix()}:{node.value.lineno}")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and len(node.args) == 2
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "min_sources"
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value != 1
                ):
                    raised.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert raised == [], f"min_sources is set above 1 somewhere now: {raised}"

    index = (ROOT / "products" / "README.md").read_text(encoding="utf-8")
    assert "has never fired" in index


def test_the_declared_and_unused_table_lists_every_row_it_should():
    """A table of what is unwired is itself a claim, so its shape is pinned."""
    index = (ROOT / "products" / "README.md").read_text(encoding="utf-8")
    table = index[index.index("| Declared | Reality |") :]
    table = table[: table.index("\n\n")]
    rows = [line for line in table.splitlines() if line.startswith("|")][2:]
    assert len(rows) == 6, f"{len(rows)} rows in the unwired table"
    for needle in ("keys.py", "agent_rows", "llm.Cached", "UNDER_CORROBORATED", "to_langgraph"):
        assert needle in table, needle


# -- what every product's README says the gate does ---------------------------


def test_no_readme_claims_the_gate_checks_what_the_model_wrote():
    """The sentence was in all twenty, and it was false.

    "The gate drops anything the model wrote that no tool receipt supports" - while no
    node in any of the twenty writes `claims` or `issued_receipts`, both arrive in the
    request body, and the same READMEs list them as input keys fifteen lines later. The
    two model nodes write `summary` and `draft`, which the gate never reads.
    """
    readmes = [
        *sorted((ROOT / "products").glob("[0-9]*/README.md")),
        ROOT / "products" / "README.md",
    ]
    assert len(readmes) == 21, [p.parent.name for p in readmes]

    for path in readmes:
        text = path.read_text(encoding="utf-8")
        assert "anything the model wrote that no tool receipt supports" not in text, (
            f"{path.parent.name}: the false claim is back"
        )


def test_every_product_readme_says_where_the_claims_come_from():
    """The replacement has to be present, not just the old sentence absent."""
    for path in sorted((ROOT / "products").glob("[0-9]*/README.md")):
        text = path.read_text(encoding="utf-8")
        assert "The gate drops any claim whose receipts were not issued" in text, path.parent.name
        assert "arrive in the request body" in text, path.parent.name


def test_no_node_in_any_product_writes_claims_or_receipts():
    """The premise of the correction, asserted rather than assumed.

    If a product ever grows a node that produces claims, this fails - and the README
    sentence it fails on is the one that should then change back.
    """
    import ast

    writers: list[str] = []
    for src in sorted((ROOT / "products").glob("[0-9]*/src")):
        for path in sorted(src.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # A dict literal with "claims" or "issued_receipts" as a key, returned
                # by a node. `gate.from_state` READS them, which is not writing them.
                if not isinstance(node, ast.Dict):
                    continue
                keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
                if keys & {"claims", "issued_receipts"}:
                    writers.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not writers, (
        "a node now produces claims or receipts, so the gate can be a check on the "
        f"model and the READMEs should say so: {writers}"
    )


# -- the table as the README prints it, against the table the code builds -----------
#
# `test_the_table_grants_something_and_denies_everyone_else` checks that a table exists
# and is default-deny. Nothing compared it to the table printed beside it, and all
# twenty disagreed:
#
#   * every product wrote plural collection names where the code grants dotted field
#     patterns - `leads` against `lead.*`, `matches` against `match.*`, `drafts`
#     against `draft.*`, `summaries.draft` against `summary.draft`. A reader checking
#     whether a field is writable would have looked up a name that is not in the table;
#   * thirty-two rows named an agent with no grant anywhere in the product -
#     `results-router`, `preauth-packer`, `qa-sampler` and the rest. Default-deny means
#     they may write nothing, and a row saying otherwise is read as a guarantee;
#   * `brand-guard` was granted in code and documented nowhere;
#   * two rows contradicted themselves, putting a field in the Never column that the
#     same agent is granted at PROPOSE.
#
# The May-write column is now generated from `agents.authority()`. The Never column is
# still prose - no code produces "any clinical field" - but it may not name a field the
# same agent is granted, which is the one part of it that can be checked.

AUTHORITY_ROW = re.compile(r"^\|\s*`([\w-]+)`\s*\|(.*?)\|(.*?)\|\s*$", re.MULTILINE)
TICKED_FIELD = re.compile(r"`([\w.*-]+)`")


def _documented_table(package_dir: Path) -> dict[str, tuple[str, str]]:
    """Agent -> (may-write cell, never cell), from the README's authority table."""
    lines = (package_dir / "README.md").read_text(encoding="utf-8").split("\n")
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == "| Agent | May write | Never |"),
        None,
    )
    if start is None:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        found = AUTHORITY_ROW.match(line)
        if found:
            out[found.group(1)] = (found.group(2).strip(), found.group(3).strip())
    return out


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_the_readme_table_lists_exactly_the_agents_the_code_grants(product, package):
    table = table_for(package)
    # Every agent the code names, including one whose only entry is an explicit
    # NEVER: `pr-opener` holds exactly that, and it is a statement the table makes
    # rather than an absence, so it belongs in the printed table too.
    granted = {agent for (agent, _field) in table._grants}  # noqa: SLF001 - its own repo
    documented = _documented_table(ROOT / "products" / product)
    assert documented, f"{product}: no authority table in the README"
    assert set(documented) == granted, (
        f"{product}: README lists {sorted(set(documented) - granted)} with no grant, "
        f"and omits {sorted(granted - set(documented))}"
    )


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_every_granted_field_appears_in_the_may_write_column(product, package):
    """The column is generated from the code, so a grant added without regenerating it
    is what this catches - which is exactly how the plural names survived."""
    table = table_for(package)
    documented = _documented_table(ROOT / "products" / product)
    for (agent, field_name), level in table._grants.items():  # noqa: SLF001
        if level is Level.NEVER:
            continue
        cell = documented.get(agent, ("", ""))[0]
        assert f"`{field_name}`" in cell, (
            f"{product}: {agent} is granted {field_name}, cell: {cell}"
        )


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_the_may_write_column_names_no_field_the_code_does_not_grant(product, package):
    table = table_for(package)
    grants = {}
    for (agent, field_name), level in table._grants.items():  # noqa: SLF001
        grants.setdefault(agent, {})[field_name] = level
    documented = _documented_table(ROOT / "products" / product)
    for agent, (may_write, _never) in documented.items():
        for ref in TICKED_FIELD.findall(may_write):
            level = grants.get(agent, {}).get(ref)
            assert level is not None and level is not Level.NEVER, (
                f"{product}: README says {agent} may write {ref}; the code says "
                f"{level.value if level else 'nothing'}"
            )


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_no_never_cell_names_a_field_the_same_agent_may_write(product, package):
    """The two that did said a clinician signs `summaries.final` and that `deal.amount`
    may never be written - both fields the agent holds a PROPOSE grant on. A row that
    contradicts itself is worse than either half of it alone."""
    table = table_for(package)
    # WRITE only. A PROPOSE field in the Never column is not a contradiction - "may
    # never write `summary.final` outright, a clinician signs" is exactly what a
    # PROPOSE grant means, and that row says so. A WRITE field there is flatly false.
    writable = {}
    for (agent, field_name), level in table._grants.items():  # noqa: SLF001
        if level is Level.WRITE:
            writable.setdefault(agent, set()).add(field_name)
    documented = _documented_table(ROOT / "products" / product)
    for agent, (_may, never) in documented.items():
        for ref in TICKED_FIELD.findall(never):
            assert ref not in writable.get(agent, set()), (
                f"{product}: {agent} may never write {ref}, and is granted it"
            )


#: What a cell says before this marker is written outright; what comes after it is
#: proposed for a human to commit. Five grants across three products are PROPOSE.
PROPOSE_MARKER = "propose only:"


def _cell_halves(cell: str) -> tuple[str, str]:
    """(written outright, proposed). A cell with no marker proposes nothing."""
    written, _, proposed = cell.partition(PROPOSE_MARKER)
    return written, proposed


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_the_column_says_which_fields_are_proposed_and_which_are_written(product, package):
    """A level, not just a name.

    The two tests above compare the set of field names in the cell against the set in
    the table; neither reads the level. `writer` may write `draft.*` and may only
    propose `message.send`, and a cell listing both without the distinction reads as
    authority to send - which is the exact claim the authority table exists to deny.
    """
    table = table_for(package)
    documented = _documented_table(ROOT / "products" / product)
    for (agent, field_name), level in sorted(table._grants.items()):  # noqa: SLF001
        if level is Level.NEVER:
            continue
        written, proposed = _cell_halves(documented.get(agent, ("", ""))[0])
        ticked = f"`{field_name}`"
        if level is Level.PROPOSE:
            assert ticked in proposed, (
                f"{product}: {agent} may only PROPOSE {field_name}, and the README "
                f"prints it as a field it writes: {documented.get(agent, ('', ''))[0]!r}"
            )
        else:
            assert ticked in written, (
                f"{product}: {agent} may WRITE {field_name}, and the README prints it "
                f"as proposed only: {documented.get(agent, ('', ''))[0]!r}"
            )


def test_a_product_with_a_propose_grant_exists_to_check():
    """Both branches above have to be reachable, or half of this is untested.

    Five of the 107 grants are PROPOSE, in revenue-desk, ward-sync and bid-desk. A
    repository with none would pass the test above over the WRITE branch alone and
    say nothing about the distinction it is named for.
    """
    levels = {}
    for name, package in sorted(PRODUCTS.items()):
        for key, level in table_for(package)._grants.items():  # noqa: SLF001
            levels.setdefault(level, []).append((name, *key))
    assert len(levels[Level.PROPOSE]) == 5, levels[Level.PROPOSE]
    assert {p for p, _a, _f in levels[Level.PROPOSE]} == {
        "01_revenue-desk",
        "02_ward-sync",
        "08_bid-desk",
    }, levels[Level.PROPOSE]
    assert len(levels[Level.WRITE]) > 50, len(levels[Level.WRITE])


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_the_propose_half_of_a_cell_names_nothing_ungranted(product, package):
    """ "propose only: `x`" where `x` is granted to nobody is the same defect as the
    thirty-two documented agents with no grant, one column further in."""
    table = table_for(package)
    grants = {}
    for (agent, field_name), level in table._grants.items():  # noqa: SLF001
        grants.setdefault(agent, {})[field_name] = level
    documented = _documented_table(ROOT / "products" / product)
    for agent, (may_write, _never) in documented.items():
        _written, proposed = _cell_halves(may_write)
        for ref in TICKED_FIELD.findall(proposed):
            assert grants.get(agent, {}).get(ref) is Level.PROPOSE, (
                f"{product}: {agent} is said to propose {ref}; the code says "
                f"{grants.get(agent, {}).get(ref)}"
            )
