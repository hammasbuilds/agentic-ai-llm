"""Every backticked code reference in the markdown names something the code defines.

An independent review listed "documentation describing absent code" as a finding and
gave a long list. This is the checkable half of it: a name in backticks that looks like
code and is defined nowhere. One was left when the rest had been fixed -
`patient.demographics`, in ward-sync's write-authority table - and following it found
the larger thing, which was not a name at all but a whole table nothing compared to its
producer. See `test_product_authority.py` for that.

The shapes considered are the ones that can only be code: `name()`, `a.b()`, and a
dotted `module.name` where every part is identifier-shaped. Prose in backticks, file
paths, CLI flags, shell lines and topic names are left alone, so this does not become a
spell-checker for the prose around the code.

Resolution is by name, not by import: a definition anywhere in the repository satisfies
a reference anywhere. That is deliberately loose. The strict version would need the
import graph, and the failure this is for is a name that exists nowhere - a function
that was renamed, or one that was only ever described.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PARTS = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache", "build", "dist"}

#: `name()` and `a.b()`.
CALL = re.compile(r"`([A-Za-z_][\w.]*)\(\)`")
#: A dotted lowercase-led path: `module.thing`, `agentplatform.authority`.
DOTTED = re.compile(r"`([a-z_]\w*(?:\.[A-Za-z_]\w*)+)`")

#: References that are real but unresolvable by name - a field of an external library,
#: a name only in a changelog. Each needs the reason beside it.
ALLOWED: dict[str, str] = {}


def _python() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not (SKIP_PARTS & set(p.parts))]


def _markdown() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not (SKIP_PARTS & set(p.parts))]


def _defined(files: list[Path]) -> tuple[set[str], set[str], set[str]]:
    names: set[str] = set()
    qualified: set[str] = set()
    modules: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - deliberately broken fixtures
            continue
        modules.add(path.stem)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                qualified.add(f"{path.stem}.{node.name}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                        qualified.add(f"{path.stem}.{target.id}")
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
                qualified.add(f"{path.stem}.{node.target.id}")
            elif isinstance(node, ast.arg):
                names.add(node.arg)
    return names, qualified, modules


def test_every_backticked_code_reference_resolves():
    files = _python()
    docs = _markdown()
    assert len(files) > 200, len(files)
    assert len(docs) > 20, len(docs)

    names, qualified, modules = _defined(files)
    assert len(names) > 1_000, len(names)

    # Attributes, dict keys and dataclass fields are reached by text: they are not
    # definitions, but a README naming one is naming something that exists.
    everything = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)

    checked = 0
    missing: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for pattern in (CALL, DOTTED):
            for found in pattern.finditer(text):
                ref = found.group(1)
                checked += 1
                if ref in ALLOWED:
                    continue
                tail = ref.split(".")[-1]
                if ref in qualified or tail in names or tail in modules:
                    continue
                if re.search(rf"\b{re.escape(tail)}\b", everything):
                    continue
                missing.append(f"{doc.relative_to(ROOT).as_posix()}: {ref}")

    # A sweep that matched nothing passes, and this one reads every README.
    assert checked > 300, checked
    assert not missing, f"named in the markdown, defined nowhere: {sorted(set(missing))}"
