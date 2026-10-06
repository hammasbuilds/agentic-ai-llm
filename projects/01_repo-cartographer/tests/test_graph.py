"""Graph tests: resolution, the honest denominator, and ranking."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from cartographer.graph import (
    build_graph,
    entry_points,
    most_called,
    pagerank,
)
from cartographer.parse import parse_repo


def write(root: Path, rel: str, source: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


@pytest.fixture
def graph(tmp_path: Path):
    write(tmp_path, "pyproject.toml", "[project]\nname='demo'\n")
    write(
        tmp_path,
        "src/demo/util.py",
        """
        def helper(x):
            return x + 1
    """,
    )
    write(
        tmp_path,
        "src/demo/core.py",
        """
        from demo.util import helper

        class Engine:
            def run(self):
                return self.step()

            def step(self):
                return helper(1)

        def entry():
            return Engine().run()
    """,
    )
    write(
        tmp_path,
        "src/demo/cli.py",
        """
        from demo.core import entry

        def main():
            print(entry())
    """,
    )
    return build_graph(parse_repo(tmp_path))


# -- resolution -----------------------------------------------------------


def test_imported_function_resolves_to_its_definition(graph):
    callers = graph.callers("demo.util.helper")
    assert len(callers) == 1
    assert callers[0].caller == "demo.core.Engine.step"


def test_self_call_resolves_within_the_class(graph):
    callers = graph.callers("demo.core.Engine.step")
    assert [c.caller for c in callers] == ["demo.core.Engine.run"]


def test_cross_module_call_resolves(graph):
    assert graph.fan_in("demo.core.entry") == 1
    assert graph.callers("demo.core.entry")[0].caller == "demo.cli.main"


def test_builtin_calls_never_resolve_to_repo_symbols(graph):
    assert "print" not in graph.by_qualname
    assert graph.resolution.out_of_scope["print"] >= 1


# -- the honest denominator ----------------------------------------------


def test_repo_rate_excludes_calls_that_could_never_bind(graph):
    """Builtins in the denominator make every repo look unmappable.

    The same denominator mistake that made grammar-constrained decoding look
    19 points worse than plain prompting in langchain-lab 01, when it was
    actually three times more accurate.
    """
    res = graph.resolution
    assert res.in_scope_calls < res.total_calls
    assert res.repo_resolution_rate > res.resolution_rate
    assert res.repo_resolution_rate == pytest.approx(1.0)


def test_in_scope_is_resolved_plus_missed(graph):
    res = graph.resolution
    assert res.in_scope_calls == res.resolved_count + sum(res.missed.values())


def test_every_unresolved_call_is_classified(graph):
    res = graph.resolution
    assert sum(res.unresolved.values()) == sum(res.out_of_scope.values()) + sum(
        res.missed.values()
    )


# -- ranking --------------------------------------------------------------


def test_pagerank_ranks_the_depended_upon_module_highest(graph):
    ranks = pagerank(graph)
    # util is imported by core, which is imported by cli.
    assert ranks["demo.util"] > ranks["demo.cli"]


def test_pagerank_is_a_distribution(graph):
    ranks = pagerank(graph)
    assert sum(ranks.values()) == pytest.approx(1.0, abs=1e-6)


def test_entry_points_are_uncalled_public_definitions(graph):
    names = {s.name for s in entry_points(graph)}
    assert "main" in names  # nothing in the repo calls it
    assert "helper" not in names  # core calls it


def test_most_called_is_ordered_by_fan_in(graph):
    ranked = most_called(graph)
    counts = [c for _, c in ranked]
    assert counts == sorted(counts, reverse=True)


# -- the denominator, on a repository that ships with the tests ------------
#
# This is the fix the README's whole table rests on, and until now the only tests that
# exercised it were the five rows of `test_readme_numbers.py` and
# `test_real_repo_resolves_most_of_its_internal_calls` - every one of which skips when
# the sibling checkouts are not on the machine. On a fresh clone the central claim of
# the project was defended by nothing at all, which a sweep with `REPOS_ROOT` pointed
# at an empty directory makes visible: 13 of the package's tests skip, and these were
# among them.
#
# A repository small enough to write here reproduces the review's scenario exactly, so
# the behaviour is pinned wherever the suite runs.


def _six_call_sites(root: Path) -> None:
    """The shape an independent review used to get 100% out of a 67% repository.

    Six call sites, every one of them targeting a definition in this repository, and
    all but one of them written as a method on a local variable whose type an AST
    cannot infer. Dropping those from the denominator left one in-scope call, which
    resolved, which printed as 100% - while the report listed the five methods it had
    failed to bind as "called by nothing".
    """
    write(root, "pyproject.toml", "[project]\nname='six'\n")
    write(
        root,
        "src/six/engine.py",
        """
        class Engine:
            def start(self):
                return 1

            def stop(self):
                return 2

            def flush(self):
                return 3

            def reload(self):
                return 4

            def status(self):
                return 5


        def make():
            return Engine()
    """,
    )
    write(
        root,
        "src/six/app.py",
        """
        from six.engine import make

        def run():
            engine = make()
            engine.start()
            engine.stop()
            engine.flush()
            engine.reload()
            engine.status()
            return engine
    """,
    )


def test_a_method_on_an_uninferable_receiver_stays_in_the_denominator(tmp_path: Path):
    """The fix, on a repository that needs no checkout.

    `engine.start()` cannot be bound by an AST: nothing here says what `engine` is.
    What it must not do is leave the denominator. This repository defines a method
    called `start`, so the call *could* target repository code, and a call that could
    bind and did not is the definition of unresolved.
    """
    _six_call_sites(tmp_path)
    resolution = build_graph(parse_repo(tmp_path)).resolution

    in_scope = resolution.resolved_count + sum(resolution.missed.values())
    # Seven, not the six written in `_six_call_sites`: `make()` and the `Engine()`
    # construction inside it both resolve, and the five methods do not. Counted here
    # rather than rounded to the number that reads better - the whole finding this
    # defends is a denominator that quietly dropped what it could not bind.
    assert in_scope == 7, resolution.missed
    assert resolution.resolved_count == 2
    assert sum(resolution.missed.values()) == 5
    assert set(resolution.missed) == {
        "engine.start",
        "engine.stop",
        "engine.flush",
        "engine.reload",
        "engine.status",
    }

    # Two of seven, not two of two. The old denominator sent all five uninferable
    # receivers out of scope, leaving a repository that binds 29% of its in-scope
    # calls reporting 100%.
    assert resolution.repo_resolution_rate == pytest.approx(2 / 7)


def test_a_method_this_repository_never_defines_is_out_of_scope(tmp_path: Path):
    """The other half of the same decision, which is what keeps it from being a rule
    that counts everything.

    `response.json()` and `path.exists()` are calls into a third-party object and the
    standard library. Counting them unresolved would make every repository look
    unmappable, which is the mistake in the opposite direction - so "in scope" is
    decided by whether this repository defines a method of that name anywhere.
    """
    write(tmp_path, "pyproject.toml", "[project]\nname='out'\n")
    write(
        tmp_path,
        "src/out/app.py",
        """
        import json
        from pathlib import Path

        def load(response, path):
            data = response.json()
            if Path(path).exists():
                return json.dumps(data)
            return None
    """,
    )
    resolution = build_graph(parse_repo(tmp_path)).resolution

    assert not resolution.missed, resolution.missed
    assert "response.json" in resolution.out_of_scope
    assert resolution.resolved_count + sum(resolution.missed.values()) == 0


def test_the_two_rates_differ_on_the_fixture_as_they_do_in_the_table(tmp_path: Path):
    """The README's argument is the gap between the columns, and it is reproduced here.

    `resolution_rate` counts every call site including builtins, so it reads low;
    `repo_resolution_rate` counts only calls that could reach repository code. If the
    two ever coincide, one of the denominators has stopped doing its job - and until
    this test existed that check only ran where the five checkouts happen to be.
    """
    _six_call_sites(tmp_path)
    write(
        tmp_path,
        "src/six/extra.py",
        """
        def noisy(items):
            return len(sorted(set(items)))
    """,
    )
    resolution = build_graph(parse_repo(tmp_path)).resolution
    assert resolution.resolution_rate < resolution.repo_resolution_rate
    assert resolution.total_calls > resolution.resolved_count + sum(resolution.missed.values())


# -- integration against a real repository --------------------------------


def test_call_through_a_package_reexport_resolves(tmp_path: Path):
    """`from pkg import clean` where `pkg/__init__.py` re-exports it.

    The definition lives in `pkg.normalise`, not `pkg`. Resolution must follow
    the re-export chain or every call through a package facade goes unbound.
    """
    write(tmp_path, "src/pkg/__init__.py", "from .normalise import clean")
    write(tmp_path, "src/pkg/normalise.py", "def clean(s):\n    return s")
    write(
        tmp_path,
        "src/pkg/app.py",
        """
        from pkg import clean

        def run(s):
            return clean(s)
    """,
    )
    graph = build_graph(parse_repo(tmp_path))
    callers = graph.callers("pkg.normalise.clean")
    assert [c.caller for c in callers] == ["pkg.app.run"]
    assert graph.resolution.repo_resolution_rate == pytest.approx(1.0)


# Sibling checkouts live beside the monorepo, so that is the default root.
REPOS_ROOT = Path(os.environ.get("REPOS_ROOT") or Path(__file__).resolve().parents[3].parent)
REAL_REPO = REPOS_ROOT / "langchain-lab"


@pytest.mark.skipif(not REAL_REPO.exists(), reason=f"no checkout at {REAL_REPO}")
def test_real_repo_resolves_most_of_its_internal_calls():
    """Pure AST resolution should bind the large majority of repo-internal calls.

    No embeddings, no model. If this drops sharply, resolution has regressed.
    """
    graph = build_graph(parse_repo(REAL_REPO))
    assert graph.resolution.repo_resolution_rate > 0.85


@pytest.mark.skipif(not REAL_REPO.exists(), reason=f"no checkout at {REAL_REPO}")
def test_real_repo_core_module_is_the_shared_one():
    """langchain-lab's load-bearing module is its shared model registry."""
    graph = build_graph(parse_repo(REAL_REPO))
    ranks = pagerank(graph)
    top = max(ranks, key=ranks.get)
    assert top.startswith("shared.")
