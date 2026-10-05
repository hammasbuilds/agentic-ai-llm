"""Mutation operators over a Python AST.

A mutant is a single, small, *plausible* change to the source: the kind of thing
a tired person types. If the test suite still passes with the change in place,
the suite does not actually check that behaviour - whatever the coverage report
says about the line having run.

Every operator here produces a program that is still syntactically valid and
usually still runs. Operators that mostly produce crashes are not useful: a
mutant killed by an import error tells you nothing about the tests.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path

# -- the operator table ---------------------------------------------------

_COMPARE_SWAPS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}

_BINOP_SWAPS: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div,
    ast.Mod: ast.Mult,
    ast.Pow: ast.Mult,
}

_BOOLOP_SWAPS: dict[type[ast.boolop], type[ast.boolop]] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}


@dataclass(frozen=True)
class Mutant:
    """One candidate change, identified well enough to reproduce it."""

    mid: str  # stable id: "path:line:operator:index"
    path: str  # repo-relative posix path
    line: int
    col: int
    operator: str  # "compare", "binop", "constant", ...
    before: str
    after: str
    source: str  # the full mutated module source

    @property
    def label(self) -> str:
        return f"{self.path}:{self.line} {self.operator} {self.before} -> {self.after}"


class _Collector(ast.NodeVisitor):
    """Finds every mutable site. Collecting and mutating are separate passes.

    Mutating during the walk would invalidate the node positions the next
    mutation needs, so sites are gathered first and applied one at a time to a
    fresh copy of the tree.
    """

    def __init__(self) -> None:
        self.sites: list[tuple[str, ast.AST, int]] = []  # (operator, node, slot)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        for i, op in enumerate(node.ops):
            if type(op) in _COMPARE_SWAPS:
                self.sites.append(("compare", node, i))
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:  # noqa: N802
        if type(node.op) in _BINOP_SWAPS:
            self.sites.append(("binop", node, 0))
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        if type(node.op) in _BOOLOP_SWAPS:
            self.sites.append(("boolop", node, 0))
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:  # noqa: N802
        if isinstance(node.op, ast.Not):
            self.sites.append(("not", node, 0))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if _constant_replacement(node.value) is not _NO_CHANGE:
            self.sites.append(("constant", node, 0))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        # `return expr` -> `return None`. Skips bare returns and `return None`.
        if node.value is not None and not _is_none(node.value):
            self.sites.append(("return", node, 0))
        self.generic_visit(node)


_NO_CHANGE = object()


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _constant_replacement(value: object):
    """What to change a literal into, or _NO_CHANGE to leave it alone.

    Docstrings and most strings are skipped: swapping a message changes nothing
    a good test would assert on, and floods the report with equivalent mutants.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return 0 if value != 0 else 1
    if isinstance(value, float):
        return 0.0 if value != 0.0 else 1.0
    return _NO_CHANGE


def _describe(operator: str, node: ast.AST, slot: int) -> tuple[str, str]:
    """Human-readable before/after for the report."""
    if operator == "compare":
        op = node.ops[slot]  # type: ignore[attr-defined]
        return _opname(op), _opname(_COMPARE_SWAPS[type(op)]())
    if operator == "binop":
        return _opname(node.op), _opname(_BINOP_SWAPS[type(node.op)]())  # type: ignore[attr-defined]
    if operator == "boolop":
        return _opname(node.op), _opname(_BOOLOP_SWAPS[type(node.op)]())  # type: ignore[attr-defined]
    if operator == "not":
        return "not x", "x"
    if operator == "constant":
        v = node.value  # type: ignore[attr-defined]
        return repr(v), repr(_constant_replacement(v))
    if operator == "return":
        return "return <expr>", "return None"
    return operator, operator


_OPNAMES = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.In: "in",
    ast.NotIn: "not in",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.And: "and",
    ast.Or: "or",
}


def _opname(op: ast.AST) -> str:
    return _OPNAMES.get(type(op), type(op).__name__)


def _apply(tree: ast.AST, operator: str, target_pos: tuple[int, int], slot: int) -> bool:
    """Apply one mutation to a fresh tree, located by position rather than identity.

    The tree is a deep copy, so the node object collected earlier is not the one
    in this tree. Position plus operator kind identifies it unambiguously.
    """
    for node in ast.walk(tree):
        pos = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
        if pos != target_pos:
            continue
        if operator == "compare" and isinstance(node, ast.Compare):
            op = node.ops[slot]
            if type(op) in _COMPARE_SWAPS:
                node.ops[slot] = _COMPARE_SWAPS[type(op)]()
                return True
        elif operator == "binop" and isinstance(node, ast.BinOp):
            if type(node.op) in _BINOP_SWAPS:
                node.op = _BINOP_SWAPS[type(node.op)]()
                return True
        elif operator == "boolop" and isinstance(node, ast.BoolOp):
            if type(node.op) in _BOOLOP_SWAPS:
                node.op = _BOOLOP_SWAPS[type(node.op)]()
                return True
        elif operator == "not" and isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                _replace_node(tree, node, node.operand)
                return True
        elif operator == "constant" and isinstance(node, ast.Constant):
            rep = _constant_replacement(node.value)
            if rep is not _NO_CHANGE:
                node.value = rep
                return True
        elif operator == "return" and isinstance(node, ast.Return):
            if node.value is not None:
                node.value = ast.Constant(value=None)
                return True
    return False


def _replace_node(tree: ast.AST, old: ast.AST, new: ast.AST) -> None:
    """Swap `old` for `new` wherever it sits in its parent."""
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, field, new)
                return
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if item is old:
                        value[i] = new
                        return


def generate(path: Path, rel: str, source: str | None = None) -> list[Mutant]:
    """Every mutant for one module.

    Returns an empty list rather than raising if the file does not parse: a repo
    with one broken file should still be measurable.
    """
    if source is None:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
    try:
        base = ast.parse(source)
    except SyntaxError:
        return []

    collector = _Collector()
    collector.visit(base)

    mutants: list[Mutant] = []
    for index, (operator, node, slot) in enumerate(collector.sites):
        pos = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
        tree = copy.deepcopy(base)
        if not _apply(tree, operator, pos, slot):
            continue
        try:
            mutated = ast.unparse(ast.fix_missing_locations(tree))
        except Exception:  # unparse can fail on exotic trees; skip that mutant
            continue
        if mutated == ast.unparse(base):
            continue  # equivalent mutant, nothing actually changed
        before, after = _describe(operator, node, slot)
        mutants.append(
            Mutant(
                mid=f"{rel}:{pos[0]}:{operator}:{index}",
                path=rel,
                line=pos[0],
                col=pos[1],
                operator=operator,
                before=before,
                after=after,
                source=mutated,
            )
        )
    return mutants
