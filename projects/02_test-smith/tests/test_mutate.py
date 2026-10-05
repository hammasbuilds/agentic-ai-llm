"""Mutation operator tests.

Each operator is checked for what it produces *and* for what it refuses to
produce. An operator that fires on the wrong node floods the report with
equivalent mutants, which is the usual reason people abandon mutation testing.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from testsmith.mutate import generate


def mutants_for(source: str):
    return generate(Path("m.py"), "m.py", textwrap.dedent(source).lstrip())


def labels(source: str) -> set[str]:
    return {f"{m.operator}:{m.before}->{m.after}" for m in mutants_for(source)}


# -- operators fire -------------------------------------------------------


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("x = a < b", "compare:<-><="),
        ("x = a > b", "compare:>->>="),
        ("x = a == b", "compare:==->!="),
        ("x = a is b", "compare:is->is not"),
        ("x = a in b", "compare:in->not in"),
    ],
)
def test_comparison_operators_swap(src: str, expected: str):
    assert expected in labels(src)


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("x = a + b", "binop:+->-"),
        ("x = a - b", "binop:-->+"),
        ("x = a * b", "binop:*->/"),
        ("x = a / b", "binop:/->*"),
    ],
)
def test_arithmetic_operators_swap(src: str, expected: str):
    assert expected in labels(src)


def test_boolean_operator_swaps():
    assert "boolop:and->or" in labels("x = a and b")


def test_not_is_removed():
    assert "not:not x->x" in labels("x = not a")


def test_return_value_becomes_none():
    assert "return:return <expr>->return None" in labels("def f():\n    return 1")


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("x = 5", "constant:5->0"),
        ("x = 0", "constant:0->1"),
        ("x = True", "constant:True->False"),
        ("x = 1.5", "constant:1.5->0.0"),
    ],
)
def test_numeric_and_boolean_constants_mutate(src: str, expected: str):
    assert expected in labels(src)


# -- operators hold fire --------------------------------------------------


def test_strings_are_not_mutated():
    """Swapping a message produces an equivalent mutant nobody should assert on."""
    assert mutants_for('x = "hello"') == []


def test_docstrings_are_not_mutated():
    assert mutants_for('def f():\n    """Explain."""\n    pass') == []


def test_bare_return_is_not_mutated():
    assert mutants_for("def f():\n    return") == []


def test_return_none_is_not_mutated():
    """`return None` -> `return None` changes nothing, so it must not be offered."""
    assert mutants_for("def f():\n    return None") == []


# -- structural guarantees ------------------------------------------------


def test_every_mutant_is_valid_python():
    src = """
        def score(values, threshold=10):
            total = 0
            for v in values:
                if v > threshold and v != 0:
                    total = total + v * 2
            return total if not total else None
    """
    produced = mutants_for(src)
    assert len(produced) > 8
    for m in produced:
        ast.parse(m.source)  # raises if the mutant is not parseable


def test_each_mutant_differs_from_the_original():
    src = "def f(a, b):\n    return a + b\n"
    original = ast.unparse(ast.parse(textwrap.dedent(src)))
    for m in mutants_for(src):
        assert m.source != original


def test_mutants_change_exactly_one_thing():
    """Two mutants of `a + b > c` must differ from each other, not compound."""
    produced = mutants_for("x = a + b > c")
    sources = {m.source for m in produced}
    assert len(sources) == len(produced)
    assert "a - b" in " ".join(sources)
    assert ">=" in " ".join(sources)
    # No single mutant contains both changes.
    for s in sources:
        assert not ("a - b" in s and ">=" in s)


def test_ids_are_unique_and_stable():
    src = "def f(a):\n    return a + 1 - 2\n"
    first = mutants_for(src)
    second = mutants_for(src)
    assert [m.mid for m in first] == [m.mid for m in second]
    assert len({m.mid for m in first}) == len(first)


def test_unparseable_file_yields_no_mutants_rather_than_raising():
    assert generate(Path("bad.py"), "bad.py", "def f(:\n") == []


def test_missing_file_yields_no_mutants(tmp_path: Path):
    assert generate(tmp_path / "nope.py", "nope.py") == []
