"""Every declared dependency against every import, in both directions.

An independent review found four kinds of mismatch at once, in a tree that ships a
compliance control called `deps-used`:

  * `langchain-core>=0.3` and `langchain-ollama>=0.2` in the root `pyproject.toml` with
    zero imports anywhere - `grep -rn langchain --include=*.py` finds only the name of
    a sibling checkout - and `"langchain"` in `keywords` advertising them;
  * `explain = ["httpx>=0.27"]` in `repo-cartographer`, an extra for an explanation
    layer that does not exist, under a banner reading "zero runtime dependencies, zero
    LLM calls, zero network";
  * `pyarrow` imported by `graph-clinic` and declared nowhere, so a clean install
    cannot run the half of its suite that reads the real dataset;
  * all twenty products declaring bare `agentplatform` while `app.py:main()` - the
    command each of their READMEs gives - imports uvicorn and wraps an `Ollama` model,
    so the documented command fails on a clean install.

The import side is read with `ast`, not with a regex: a module named in a string, a
comment or a docstring is not an import, and `grep` cannot tell the difference.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Distribution name -> the module it provides, where they differ.
MODULE_OF = {
    "python-multipart": "multipart",
    "psycopg[binary]": "psycopg",
    "kafka-python": "kafka",
    "uvicorn[standard]": "uvicorn",
    "sse-starlette": "sse_starlette",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
}

#: Declared and imported by nothing here on purpose, each with the reason. Empty is the
#: right answer; an entry is a hole, not an exemption.
NOT_IMPORTED: dict[str, str] = {
    # A server, not a library: `uvicorn.run(...)` is called, and `uvicorn[standard]`
    # pulls the loop and protocol implementations it selects at runtime.
    "uvicorn": "run() is called; the [standard] extras are loaded by uvicorn itself",
    # Declared by the product so a deployment gets it; imported only inside the
    # platform's adapters, which are a different distribution.
    "agentplatform": "the workspace package these products are built on",
    # Loaded by starlette, not by this code. `Jinja2Templates(directory=...)` renders
    # every page and `await request.form()` parses every submit; neither imports the
    # library here, and both fail at runtime without it. A real dependency that an
    # import graph cannot see, which is why the reason is written down rather than the
    # line deleted.
    "jinja2": "starlette's Jinja2Templates imports it; every page render needs it",
    "multipart": "starlette parses `await request.form()` with it; /run posts a form",
}

PROJECTS = [
    ROOT / "pyproject.toml",
    *sorted((ROOT / "projects").glob("*/pyproject.toml")),
    *sorted((ROOT / "products").glob("*/pyproject.toml")),
]


def declared(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """(required, {extra: names}) as module names."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))["project"]

    def modules(specs) -> set[str]:
        out = set()
        for spec in specs:
            name = spec.split(">=")[0].split("==")[0].split("[")[0].strip()
            bracketed = spec.split(">=")[0].split("==")[0].strip()
            out.add(MODULE_OF.get(bracketed, MODULE_OF.get(name, name.replace("-", "_"))))
        return out

    return modules(data.get("dependencies", [])), {
        extra: modules(specs) for extra, specs in (data.get("optional-dependencies") or {}).items()
    }


def imported(package_root: Path) -> set[str]:
    """Top-level modules imported anywhere under this directory, by `ast`."""
    found: set[str] = set()
    for path in sorted(package_root.rglob("*.py")):
        parts = set(path.parts)
        if {"__pycache__", ".venv", "site-packages", "node_modules"} & parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_every_project_is_checked():
    """A sweep over an empty list passes.

    33: the root, eleven projects, twenty products and the platform.
    """
    assert len(PROJECTS) == 33, [p.parent.name for p in PROJECTS]


@pytest.mark.parametrize("path", PROJECTS, ids=lambda p: p.parent.name)
def test_nothing_is_declared_that_nothing_imports(path: Path):
    """The direction that adds an install for no reason."""
    required, extras = declared(path)
    scope = path.parent
    here = imported(scope)
    # The platform's own extras are imported by the platform; a product declaring
    # `agentplatform[api,ollama]` is asking for those, and the modules land there.
    if scope != ROOT / "products" / "platform":
        here |= imported(ROOT / "products" / "platform")

    unused = sorted(
        name
        for name in (required | set().union(*extras.values(), set())) - here
        if name not in NOT_IMPORTED
    )
    assert not unused, (
        f"{path.parent.name} declares {unused}, which nothing under it imports. "
        "Remove the line, or add it to NOT_IMPORTED with the reason."
    )


def test_pyarrow_is_declared_where_it_is_imported():
    """The other direction, on the one case that had it.

    `graph-clinic`'s `hotpot.load()` imports pyarrow inside the function with a comment
    reading "optional extra", and the extra did not exist. A clean install then fails
    with ModuleNotFoundError where the tests are written to skip.
    """
    required, extras = declared(ROOT / "products" / "14_graph-clinic" / "pyproject.toml")
    assert "pyarrow" in required | set().union(*extras.values(), set())
    assert "pyarrow" in imported(ROOT / "products" / "14_graph-clinic")


@pytest.mark.parametrize(
    "path", sorted((ROOT / "products").glob("[0-9]*/pyproject.toml")), ids=lambda p: p.parent.name
)
def test_a_product_asks_for_what_its_documented_command_needs(path: Path):
    """`python -m <pkg>.app` is in all twenty READMEs and needs uvicorn and httpx.

    Declared bare, `agentplatform` brings neither: the platform keeps them in its `api`
    and `ollama` extras so its own deterministic core installs with nothing. A product
    that documents the serving command has to ask for them.
    """
    required, _ = declared(path)
    assert required == {"agentplatform[api,ollama]".replace("-", "_")} or required == {
        "agentplatform"
    }, required
    raw = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["dependencies"]
    assert raw == ["agentplatform[api,ollama]"], (path.parent.name, raw)


def test_the_root_keywords_do_not_advertise_an_unused_library():
    """`"langchain"` was in `keywords` for two dependencies nothing imported."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    here = imported(ROOT / "apps") | imported(ROOT / "projects") | imported(ROOT / "products")
    for keyword in data.get("keywords", []):
        module = keyword.replace("-", "_")
        # Compared after the same `-` -> `_` normalisation as `module`, which the first
        # version did not do, so "swe-bench" never matched "swe_bench" and the subject
        # word was checked as though it were a package.
        if module in ("llm", "agents", "evaluation", "mbpp", "humaneval", "swe_bench", "htmx"):
            continue  # subject-matter words, not package names
        assert module in here, f"keywords advertises {keyword!r}, which nothing imports"
