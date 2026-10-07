"""No top-level definition is referenced only by prose.

An independent review listed dead code as a finding without naming it, so it got
measured. The first version of this check was both too narrow and too generous, and a
second reviewer took it apart:

  * **Scope.** It skipped any file without `src` in its path. `apps/` has no `src/`
    directory, so the whole measurement engine, `apps/_platform`, `scripts/` and
    `worker.py` were outside it - the majority of the repository's definitions, under
    a docstring claiming to cover "the repository".
  * **Collision.** It counted a use as `\\bname\\b` anywhere in the tree, so any
    unrelated identifier of the same name kept a definition alive. `trees.coverage()`
    scored dozens of uses from a `coverage` in test-smith's runner, in claims-floor's
    agents and in hermes' tests, while nothing called it. It was presented in a commit
    message as this check's find; it was found by reading.

Both are fixed by resolving references instead of matching text. For each file, its
imports say which modules it can see, and a reference counts as a use of
`module.name` only from the defining module itself or from a file that imports that
module. That resolution is what lets the scope widen to the whole tree - without it,
widening would only have multiplied the collisions.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PARTS = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache", "build", "dist"}

#: Definitions reached without a resolvable reference, with the reason each one is.
#: A name here is a claim that something outside the import graph finds it.
NAMED_INDIRECTLY: dict[str, str] = {
    "main": "console-script entry point, named in each pyproject.toml",
    "app": "ASGI application object, found by name by uvicorn",
    "runner": "passed to `apps/_platform/base.create_app` by each app module",
    "Handler": "BaseHTTPRequestHandler subclass, instantiated by http.server",
}


def python_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not (SKIP_PARTS & set(p.parts))]


def _module_key(path: Path) -> str:
    """The name a cross-file reference would carry: the file's stem.

    Deliberately not a full dotted path. These are 33 independent packages with
    overlapping layouts, several importable under different roots depending on which
    `src` is on `sys.path`, so a dotted name resolves differently per package. The
    stem is what both `from .trees import coverage` and `trees.coverage` carry.
    """
    return path.stem


def _imported_names(tree: ast.AST) -> set[str]:
    """Names this file imports from somewhere. Importing a name is using it.

    Including the ORIGINAL name of an aliased import: `from .web import html as
    console_html` binds `console_html`, so nothing in the file ever mentions `html`
    and the definition looked unreferenced. The import is the reference.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            out.update(alias.name.split(".")[-1] for alias in node.names)
    return out


def _visible_modules(tree: ast.AST) -> set[str]:
    """The module names this file imports, in any form."""
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                seen.add(alias.name.split(".")[-1])
                if alias.asname:
                    seen.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.update(part for part in node.module.split(".") if part)
            for alias in node.names:
                # `from .trees import coverage` makes `trees` visible and binds the
                # name; either way the module counts as imported here.
                seen.add(alias.asname or alias.name)
    return seen


def _referenced_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(bare names, attribute names) used in this file.

    Kept apart because they resolve differently. A bare `coverage` means whatever
    `coverage` this file can see, so counting it as a use needs the defining module to
    be imported here - that requirement is what stopped an unrelated `coverage` in
    test-smith's runner from keeping `trees.coverage` alive.

    An attribute, `agents.commit`, cannot be resolved that way at all: the object may
    have been passed in. `standard_graph(agents, ...)` reads `agents.triage`,
    `agents.commit`, `agents.early_exit` and `agents.on_exit` off a module it never
    imports, and those functions are defined once per product. So an attribute match
    counts wherever it appears, which is weaker and is the honest limit of reading
    imports.
    """
    names: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    return names, attributes


def _definitions(tree: ast.AST) -> set[str]:
    """Top-level definitions, minus the ones a test runner finds by name.

    A `test_*` function is an entry point: pytest collects it by name and nothing
    imports it, so every one of them looks dead to an import-graph check. So does a
    fixture, which pytest resolves by argument name. Excluding them is not a gap -
    `tests/test_documented_counts.py` already asserts every suite's size, so a test
    that stopped being collected shows up there as a count that moved.
    """
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    out = set()
    for node in tree.body:
        if not isinstance(node, kinds) or node.name.startswith("__"):
            continue
        if node.name.startswith("test_") or node.name.startswith("Test"):
            # pytest collects both by name. The nineteen `TestXxx` conformance
            # classes are the clearest case: each subclasses
            # `agentplatform.conformance.StandardProductTests` and is never imported
            # by anything.
            continue
        decorators = {
            getattr(d, "attr", getattr(d, "id", None)) for d in getattr(node, "decorator_list", [])
        } | {
            getattr(getattr(d, "func", None), "attr", None)
            for d in getattr(node, "decorator_list", [])
        }
        if "fixture" in decorators:
            continue
        out.add(node.name)
    return out


def _exported(tree: ast.AST) -> set[str]:
    """Names in `__all__` - the one string literal that counts as a use."""
    out: set[str] = set()
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))):
            continue
        if not any(getattr(t, "id", None) == "__all__" for t in node.targets):
            continue
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.add(element.value)
    return out


def _parsed() -> dict[Path, ast.AST]:
    out: dict[Path, ast.AST] = {}
    for path in python_files():
        try:
            out[path] = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - deliberately broken fixtures
            continue
    return out


def test_the_whole_tree_is_in_scope():
    """The first version skipped any path without `src` in it, which is most of this
    repository. Asserted so the scope cannot narrow again unnoticed."""
    files = python_files()
    assert len(files) > 300, len(files)
    outside_src = [p for p in files if "src" not in p.parts]
    assert len(outside_src) > 100, f"only {len(outside_src)} files outside a src/ tree"
    assert any("_engine" in p.parts for p in files), "the measurement engine"
    assert any("_platform" in p.parts for p in files), "the app platform"


def test_every_definition_has_a_resolvable_reference():
    parsed = _parsed()
    assert len(parsed) > 300, len(parsed)

    defined: dict[str, list[Path]] = defaultdict(list)
    for path, tree in parsed.items():
        for name in _definitions(tree):
            defined[f"{_module_key(path)}.{name}"].append(path)
    assert len(defined) > 1_000, len(defined)

    visible = {path: _visible_modules(tree) for path, tree in parsed.items()}
    referenced = {}
    attributes: set[str] = set()
    imported: set[str] = set()
    for path, tree in parsed.items():
        names, attrs = _referenced_names(tree)
        referenced[path] = names
        attributes |= attrs
        imported |= _imported_names(tree)
    exported: set[str] = set()
    for tree in parsed.values():
        exported |= _exported(tree)

    dead = []
    for qualified, where in sorted(defined.items()):
        module, _, name = qualified.partition(".")
        if name in NAMED_INDIRECTLY or name in exported or name in attributes:
            continue
        if name in imported:
            continue
        used = any(
            name in referenced[path] and (path in where or module in visible[path])
            for path in parsed
        )
        if not used:
            dead.append(f"{where[0].relative_to(ROOT).as_posix()}: {name}")

    assert not dead, (
        "referenced nowhere that can see them - delete them, or find the caller they "
        f"should have had: {dead}"
    )


def test_the_ones_that_were_found_are_accounted_for():
    """Named, because a count alone is satisfied by deleting something else."""
    pilot = (ROOT / "projects/04_migration-pilot/src/pilot/apply.py").read_text(encoding="utf-8")
    assert "RewriteRejected" not in pilot, "the superseded exception is back"

    charts = (ROOT / "projects/08_csv-analyst/src/csvanalyst/charts.py").read_text(encoding="utf-8")
    assert "is_finite" in charts, "the caller `is_finite` was given is gone"


def test_an_entry_in_the_allowlist_has_a_reason():
    """An allowlist is a list of claims. One without a reason is a silenced failure."""
    assert NAMED_INDIRECTLY, "nothing is allowed through, which is the better state"
    for name, reason in NAMED_INDIRECTLY.items():
        assert len(reason) > 20, f"{name}: {reason!r} does not say what finds it"
