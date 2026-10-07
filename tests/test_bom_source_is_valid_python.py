"""A file beginning with a BOM is a valid Python file, and four tools said it was not.

CPython reads and runs `\\ufeff`-prefixed source; `compile()` accepts the bytes. Reading
it with `encoding="utf-8"` keeps the mark as a character and `ast.parse` then fails, so
`cartographer`, `test-smith`, `review-bot` and `migration-pilot` each reported a valid
module as a syntax error.

Cartographer's case is worse than a wrong message. A module that does not parse
contributes no definitions, so every call into it counts as unresolved - a BOM lowers the
repo-call resolution rate, which is the figure that project's README is built on, and
nothing in the output says why.

`utf-8-sig` consumes the mark when it is there and is `utf-8` when it is not. Three
projects in this repository already use it - `csv-analyst` has the comments explaining
why - and the four that read Python source did not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

BOM = b"\xef\xbb\xbf"

#: Reads of something that is not Python source, where plain utf-8 is right. Named
#: with the file, because the rule below is about `.py` files being parsed, and a
#: JSON report this package wrote itself has no BOM and no `ast.parse` behind it.
NOT_PYTHON_SOURCE = {
    "projects/02_test-smith/src/testsmith/coverage.py:126": "its own JSON report",
}

#: The four packages that parse Python source with `ast`, and the `src` they need.
AST_READERS = {
    "01_repo-cartographer": "cartographer",
    "02_test-smith": "testsmith",
    "03_review-bot": "reviewbot",
    "04_migration-pilot": "pilot",
}


def _package(tmp_path: Path) -> Path:
    """Two modules, one of them BOM'd, with a call from the plain one into it."""
    root = tmp_path / "pkg_root"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "lib.py").write_bytes(BOM + b"def helper():\n    return 1\n")
    (root / "pkg" / "caller.py").write_text(
        "from pkg.lib import helper\n\n\ndef go():\n    return helper()\n", encoding="utf-8"
    )
    return root


def test_the_premise_holds_for_python_itself():
    """If CPython refused these files there would be nothing to fix."""
    source = BOM + b"VALUE = 1\n"
    compile(source, "<bom>", "exec")  # raises if the premise is wrong


@pytest.mark.parametrize("project", sorted(AST_READERS))
def test_no_ast_reader_decodes_source_as_plain_utf8(project: str):
    """The rule, so a fifth reader is covered by existing.

    Read as text rather than run, because the four read in four different places and
    what they share is the decode. A `utf-8` read of a `.py` file is the defect.
    """
    src = ROOT / "projects" / project / "src"
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{n}"
        for path in src.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if 'read_text(encoding="utf-8"' in line
        and "utf-8-sig" not in line
        and f"{path.relative_to(ROOT).as_posix()}:{n}" not in NOT_PYTHON_SOURCE
    ]
    assert offenders == [], (
        f"{offenders} read Python source as plain utf-8, so a file with a BOM is "
        "reported as a syntax error. Use utf-8-sig, which is identical without one."
    )


def test_cartographer_parses_a_bom_module_and_resolves_into_it(tmp_path: Path):
    """The consequence that is not a message: a lowered headline rate.

    One call, from a plain module into a BOM'd one. With the BOM mishandled the module
    contributes no definitions, the call resolves to nothing, and the repo-call
    resolution rate reads 0% where the answer is 100%.
    """
    sys.path.insert(0, str(ROOT / "projects" / "01_repo-cartographer" / "src"))
    from cartographer.graph import build_graph
    from cartographer.parse import parse_repo

    parsed = parse_repo(_package(tmp_path))
    assert parsed.parse_errors == [], parsed.parse_errors

    resolution = build_graph(parsed).resolution
    assert resolution.in_scope_calls == 1, resolution.in_scope_calls
    assert resolution.resolved_count == 1, dict(resolution.missed)
    assert resolution.repo_resolution_rate == 1.0


def test_the_cli_of_each_reader_does_not_call_a_bom_file_broken(tmp_path: Path):
    """End to end, through the command a reader actually runs.

    `cartographer map` is the one with a number attached; the others are checked for
    not reporting the file as unparseable, which is the shared symptom.
    """
    root = _package(tmp_path)
    done = subprocess.run(
        [sys.executable, "-m", "cartographer.cli", "map", str(root)],
        cwd=str(ROOT / "projects" / "01_repo-cartographer"),
        capture_output=True,
        text=True,
        errors="replace",
        env={**_env("01_repo-cartographer"), "PYTHONIOENCODING": "utf-8"},
        timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "did not parse" not in done.stdout, done.stdout
    assert "1 of 1 repo-internal calls resolved  (100%)" in done.stdout, done.stdout


def _env(project: str) -> dict:
    import os

    src = ROOT / "projects" / project / "src"
    return {**os.environ, "PYTHONPATH": str(src)}
