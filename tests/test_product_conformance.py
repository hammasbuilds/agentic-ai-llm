"""Every product subclasses the shared conformance tests, and sets all four fields.

The six end-to-end tests used to be pasted into nineteen `tests/test_graph.py` files -
same six names, same bodies, 2,746 lines of which maybe 200 said anything about a
particular product. They now live in `agentplatform.conformance` and each product
declares what differs: the payload a caller sends, the override that lets the graph
finish without generating, and the name that result carries.

The numbers are measured below rather than recalled. "Around 2,400" here and "800
lines in total" in the commit message were both estimates written as counts: the
nineteen copies were 2,746 lines, the nineteen subclasses that replaced them are 819,
and `conformance.py` is 177. `git show 6b9940c^:products/02_ward-sync/tests/test_graph.py`
is where the before side comes from.

Consolidating moves the risk rather than removing it. The nineteen copies could drift
apart; one shared base can instead be *not inherited from*, or inherited from with a
field left unset, and a product that does that stops testing its own graph while the
suite stays green and the count stays the same. That is the failure this file exists
to catch, and it is the only new one the refactor introduces.

`01_revenue-desk` is exempt by name. It is the worked example the products README
points at - "every graph shape appears in it exactly once" - and reading the whole run
spelled out in one file is what it is for. Exempt by name, not by a condition, so
adding a second exemption is a visible edit here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products"

#: The worked example, which spells its run out instead of inheriting it.
BY_HAND = {"01_revenue-desk"}

#: What a subclass must set. Each one is a thing that genuinely differs per product;
#: a default for any of them would let a product inherit someone else's payload.
REQUIRED = ("agents", "runtime", "base_payload", "early_exit_payload", "early_exit_result")

PACKAGES = sorted(
    p
    for p in PRODUCTS.iterdir()
    if (p / "tests" / "test_graph.py").is_file() and p.name != "platform"
)


def test_the_products_are_all_here():
    """A sweep over an empty list passes, and this one is built from the directory."""
    assert len(PACKAGES) == 20, [p.name for p in PACKAGES]
    assert {p.name for p in PACKAGES} >= BY_HAND


@pytest.mark.parametrize("package", PACKAGES, ids=[p.name for p in PACKAGES])
def test_each_product_declares_every_conformance_field(package: Path):
    """Read with `ast`, so nothing is imported and no product's dependencies are
    needed. A missing field is the failure: it would leave the base class reading an
    empty payload, and five of the six tests would pass over nothing."""
    source = (package / "tests" / "test_graph.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            getattr(base, "id", getattr(base, "attr", None)) == "StandardProductTests"
            for base in node.bases
        )
    ]

    if package.name in BY_HAND:
        assert not classes, f"{package.name} is listed as written by hand"
        assert "def test_the_whole_product_runs_end_to_end" in source
        return

    assert len(classes) == 1, f"{package.name}: expected one subclass, found {len(classes)}"
    assigned = {
        target.id
        for stmt in classes[0].body
        if isinstance(stmt, ast.Assign)
        for target in stmt.targets
        if isinstance(target, ast.Name)
    }
    missing = [field for field in REQUIRED if field not in assigned]
    assert not missing, f"{package.name} does not set {missing}"


@pytest.mark.parametrize("package", PACKAGES, ids=[p.name for p in PACKAGES])
def test_no_product_sets_an_empty_payload(package: Path):
    """An empty dict satisfies the field check above and tests nothing.

    `early_exit_payload` is also asserted non-empty inside the base class, where it
    fails as that product's own test. It is repeated here because this file is the
    one place that reads all twenty, and `base_payload` has no such guard: an empty
    one would send `{}` through the graph, which several products accept.
    """
    if package.name in BY_HAND:
        pytest.skip("written out by hand")
    tree = ast.parse((package / "tests" / "test_graph.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("base_payload", "early_exit_payload")
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                # Not a literal. One product builds its isolates with a list
                # comprehension, and a comprehension or a call is not the empty
                # dict this test is looking for - there is nothing to check.
                continue
            assert value, f"{package.name}: {node.targets[0].id} is empty"


def test_the_shared_base_holds_the_six_tests_the_copies_held():
    """The names are the contract: a product's README quotes its test count, and the
    counts did not move when nineteen files were replaced by nineteen subclasses -
    which is only true while the base holds exactly these six."""
    sys.path.insert(0, str(PRODUCTS / "platform" / "src"))
    from agentplatform.conformance import StandardProductTests

    tests = {name for name in vars(StandardProductTests) if name.startswith("test_")}
    assert tests == {
        "test_the_product_runs_end_to_end",
        "test_nothing_is_regenerated_across_the_approval",
        "test_the_early_exit_costs_no_generation",
        "test_a_failed_gather_branch_is_disclosed_to_synthesis",
        "test_an_unreceipted_claim_never_reaches_the_approver",
        "test_the_authority_table_is_default_deny",
    }, sorted(tests)


#: The line counts this file's docstring quotes. The before figure is pinned to a
#: commit because the working tree cannot produce it; the two after figures are
#: measured here, so a subclass growing back into a copy of the base shows up as this
#: test failing rather than as a sentence quietly becoming wrong.
LINES_AFTER = {"nineteen subclasses": 819, "conformance.py": 177}
BEFORE = ("6b9940c^", 2_746)


def test_the_quoted_line_counts_are_the_counts_on_disk():
    """Both numbers in the docstring used to be estimates stated as measurements."""
    subclasses = sum(
        len((package / "tests" / "test_graph.py").read_text(encoding="utf-8").splitlines())
        for package in PACKAGES
        if package.name not in BY_HAND
    )
    base = len(
        (PRODUCTS / "platform/src/agentplatform/conformance.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert subclasses == LINES_AFTER["nineteen subclasses"], subclasses
    assert base == LINES_AFTER["conformance.py"], base

    docstring = Path(__file__).read_text(encoding="utf-8").split('"""')[1]
    for what, count in sorted(LINES_AFTER.items()):
        assert str(count) in docstring, what
    assert f"{BEFORE[1]:,}" in docstring, "the before figure left the docstring"
    assert BEFORE[0] in docstring, "nothing says where the before figure is checked"


def test_consolidating_actually_removed_lines():
    """The claim the refactor rests on, as a comparison rather than two numbers.

    A base class plus nineteen subclasses that together weigh more than the copies
    did would be a worse arrangement described in the language of a better one.
    """
    before = BEFORE[1]
    after = sum(LINES_AFTER.values())
    assert after < before / 2, (after, before)


def test_the_runtime_is_wrapped_in_staticmethod():
    """Without it, Python binds `runtime` as a method and passes the class in as the
    model. It fails loudly, but it fails identically in every product at once, so it
    is worth naming rather than rediscovering."""
    for package in PACKAGES:
        if package.name in BY_HAND:
            continue
        source = (package / "tests" / "test_graph.py").read_text(encoding="utf-8")
        assert "runtime = staticmethod(runtime)" in source, package.name
