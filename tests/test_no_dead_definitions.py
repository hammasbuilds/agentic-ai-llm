"""No top-level definition under a `src/` tree is named nowhere else.

An independent review listed dead code as a finding without naming it, so it got
measured: 705 top-level functions and classes across the repository, of which two were
named nowhere but their own definition line.

Neither was a tidy deletion. `pilot.apply.RewriteRejected` was an exception superseded
by a `rejected: str | None` field on the dataclass beside it, and that one was deleted.
`csvanalyst.profile.is_finite` was the opposite: reading what it checked for found the
reason it should have had a caller. `float("1e400")` is `inf` and `1e400` matches the
numeric pattern, so one cell holding it reached three places that each did something
different with infinity - a mean of `inf` reported as computed over every value with
none skipped, a `ValueError: cannot convert float NaN to integer` out of `histogram`,
and a chart that rendered as nothing. Dead code was the symptom; a value that is not a
number travelling the length of the tool was the defect.

The check is crude by design: a name counted by text, not resolved. It can over-report
- a definition reached only through `getattr`, or named in a string - which is what
`NAMED_INDIRECTLY` is for. It is empty, and a name added to it should come with the
line that reaches it.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PARTS = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache", "build", "dist"}

#: Definitions reached without their name appearing - `getattr`, a registry keyed by
#: string, an entry point. Each needs the line that reaches it written beside it.
NAMED_INDIRECTLY: dict[str, str] = {}


def python_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not (SKIP_PARTS & set(p.parts))]


def code_only(source: str) -> str:
    """The source with comments and string literals removed.

    A name in a comment or a docstring is not a caller, and counting one as a use is
    how `trees.coverage()` passed this check while nothing called it: its own module
    docstring says "`coverage()` measures what it costs", which the first version of
    this test read as a reference. The function returned a rate over a denominator
    that silently excluded every instance whose repository could not be listed, so it
    was both uncalled and wrong - and the uncalled part is what would have found it.

    Tokenised rather than regexed, because a `#` inside a string is not a comment and
    a quote inside a comment does not open a string.
    """
    import io
    import tokenize

    kept = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source  # unparseable: fall back to counting everything
    return "\n".join(kept)


def test_every_definition_under_src_is_named_somewhere_else():
    files = python_files()
    assert len(files) > 200, len(files)
    texts = {p: code_only(p.read_text(encoding="utf-8", errors="replace")) for p in files}

    defined: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        if "src" not in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - deliberately broken fixtures
            continue
        for node in tree.body:
            kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            if isinstance(node, kinds) and not node.name.startswith("__"):
                defined[node.name].append(path)

    # A sweep over nothing passes, and this one walks the whole repository.
    assert len(defined) > 500, len(defined)

    # A name in `__all__` is a deliberate export, not prose - the only string literal
    # that counts as a use. `testsmith.runner.operator_summary` is listed there and
    # called nowhere in this repository, which is what a published package's public
    # surface looks like.
    exported: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - deliberately broken fixtures
            continue
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))):
                continue
            if not any(getattr(t, "id", None) == "__all__" for t in node.targets):
                continue
            for element in node.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    exported.add(element.value)

    # The definitions themselves are read from the real source; only the use counting
    # is done over code with the prose stripped.
    dead = []
    for name, where in sorted(defined.items()):
        if name in NAMED_INDIRECTLY or name in exported:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        uses = sum(
            len(pattern.findall(source)) - (1 if path in where else 0)
            for path, source in texts.items()
        )
        if uses == 0:
            dead.append(f"{where[0].relative_to(ROOT).as_posix()}: {name}")

    assert not dead, (
        "named nowhere but their own definition - delete them, or find the caller they "
        f"should have had: {dead}"
    )


def test_the_two_that_were_found_have_not_come_back():
    """Named outright, because a count alone would be satisfied by deleting something
    else. One was removed and one was given the caller it was missing."""
    pilot = (ROOT / "projects/04_migration-pilot/src/pilot/apply.py").read_text(encoding="utf-8")
    assert "RewriteRejected" not in pilot

    charts = (ROOT / "projects/08_csv-analyst/src/csvanalyst/charts.py").read_text(encoding="utf-8")
    assert "is_finite" in charts, "the caller it was given"
