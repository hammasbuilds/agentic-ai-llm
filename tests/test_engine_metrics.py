"""The scoring rules, which decide what each app reports.

`execute.py` is tested beside this; these are the other three pieces every published
number passes through. Each one encodes a decision about what counts, and a decision
encoded in untested code is a number nobody can defend:

`evaluate.resolve`   whether a generated path counts as the real one
`evaluate.summarize` what recall@k means when a model names nothing
`mutate.mutants`     what counts as a distinct mutation, and what is a no-op

Every case below is a decision the module's own docstrings argue for, and none of them
had a test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._engine.evaluate import (  # noqa: E402
    fabrication_rate,
    recall_at_k,
    resolve,
    summarize,
)
from apps._engine.mutate import mutants  # noqa: E402

# ---- what counts as a hit ------------------------------------------------------------


@pytest.mark.parametrize(
    "ranked,gold,k,expected",
    [
        (["a.py", "b.py", "c.py"], "a.py", 1, 1),
        (["a.py", "b.py", "c.py"], "b.py", 1, 0),
        (["a.py", "b.py", "c.py"], "b.py", 2, 1),
        (["a.py", "b.py", "c.py"], "c.py", 10, 1),  # k past the end
        ([], "a.py", 1, 0),
        (["a.py"], "", 1, 0),
    ],
)
def test_recall_at_k(ranked, gold, k, expected):
    assert recall_at_k(ranked, gold, k) == expected


# ---- what counts as the same file ----------------------------------------------------


def test_a_module_path_resolves_onto_the_repository_path():
    """The decision the docstring argues for, and the one that moved a number most.

    A generative retriever names a module, not a repository path. matplotlib's package
    lives under `lib/`, so the model answers `matplotlib/widgets.py` for a file whose
    path is `lib/matplotlib/widgets.py`. Scored literally, every correct matplotlib
    answer is a miss - which dragged one arm to 22.2% on a tier where it scored 96.1%
    on another.
    """
    listing = {"lib/matplotlib/widgets.py", "src/other/thing.py"}
    assert resolve(["matplotlib/widgets.py"], listing) == ["lib/matplotlib/widgets.py"]


def test_an_exact_path_is_left_alone():
    listing = {"lib/matplotlib/widgets.py"}
    assert resolve(["lib/matplotlib/widgets.py"], listing) == ["lib/matplotlib/widgets.py"]


def test_an_ambiguous_suffix_is_not_resolved():
    """Picking one of several would hand the arm a free guess.

    Two real files end with `utils.py`, so a model that said `utils.py` has not named
    either of them and must not be credited with one.
    """
    listing = {"a/utils.py", "b/utils.py"}
    assert resolve(["utils.py"], listing) == ["utils.py"]


def test_resolution_requires_a_directory_boundary():
    """`widgets.py` must not resolve onto `my_widgets.py`."""
    listing = {"lib/my_widgets.py"}
    assert resolve(["widgets.py"], listing) == ["widgets.py"]


def test_a_path_that_matches_nothing_survives_unchanged():
    """It has to reach the scorer as a miss, not disappear into one."""
    assert resolve(["invented/file.py"], {"real/file.py"}) == ["invented/file.py"]


def test_resolution_preserves_order_and_length():
    """Rank is the whole point of recall@k, so nothing may be reordered or dropped."""
    listing = {"lib/a.py", "x/b.py"}
    generated = ["a.py", "nope.py", "b.py"]
    out = resolve(generated, listing)
    assert len(out) == len(generated)
    assert out == ["lib/a.py", "nope.py", "x/b.py"]


# ---- what the summary says ------------------------------------------------------------


def rows(*specs):
    """summarize() wants {instance_id, repo, tier, gold, ranked, retriever}."""
    return [
        {
            "instance_id": f"i{n}",
            "repo": "r",
            "tier": spec.get("tier", "easy"),
            "gold": spec["gold"],
            "ranked": spec["ranked"],
            "retriever": spec.get("retriever", "bm25"),
        }
        for n, spec in enumerate(specs)
    ]


def test_summarize_counts_a_model_that_named_nothing_as_a_miss():
    """An empty answer is wrong, not absent. Dropping it shrinks the denominator and
    flatters the arm that refused to answer."""
    scored = rows({"gold": "a.py", "ranked": ["a.py"]}, {"gold": "b.py", "ranked": []})
    out = summarize(scored, ks=(1,))
    assert out["bm25"]["overall"]["recall@1"] == pytest.approx(0.5)


def test_summarize_on_no_results_reports_no_retrievers_rather_than_raising():
    assert summarize([], ks=(1, 5)) == {}


def test_recall_does_not_decrease_as_k_grows():
    """A property, not an example: recall@k is monotonic in k by construction, and a
    summary that violates it has mixed up its denominators."""
    out = summarize(
        rows(
            {"gold": "c.py", "ranked": ["a.py", "b.py", "c.py"]},
            {"gold": "y.py", "ranked": ["x.py"]},
            {"gold": "n.py", "ranked": ["m.py", "n.py"]},
        ),
        ks=(1, 2, 3, 5),
    )["bm25"]["overall"]
    values = [out["recall@1"], out["recall@2"], out["recall@3"], out["recall@5"]]
    assert values == sorted(values)


def test_each_retriever_is_scored_separately():
    """Two arms pooled into one number is the comparison the apps exist to make, lost."""
    out = summarize(
        rows(
            {"gold": "a.py", "ranked": ["a.py"], "retriever": "bm25"},
            {"gold": "a.py", "ranked": ["z.py"], "retriever": "model"},
        ),
        ks=(1,),
    )
    assert out["bm25"]["overall"]["recall@1"] == 1.0
    assert out["model"]["overall"]["recall@1"] == 0.0


def test_fabrication_counts_only_paths_that_exist():
    """This function is the producer of any fabrication figure the repository quotes.

    The README's "one path in five" was withdrawn, because `parse_paths` used to hand
    this function mangled strings - a bolded or line-numbered path - which it correctly
    reported as paths that do not exist. The arithmetic here was never the problem; its
    input was. What it must keep doing is count, and never resolve a near-miss away.
    """
    results = [{"repo": "r", "ranked": ["real.py", "invented.py"]}]
    out = fabrication_rate(results, {"r": ["real.py", "other.py"]})
    assert out["paths_named"] == 2
    assert out["paths_that_exist"] == 1
    assert out["rate_exists"] == pytest.approx(0.5)


def test_fabrication_reports_how_many_instances_it_could_not_check():
    """It skips any instance whose repo has no listing, and said nothing about it.

    A checker that silently drops inputs reports a rate over a denominator nobody can
    see - and the instances it drops are exactly the repositories that failed to be
    listed, which is not a random sample of them.
    """
    results = [
        {"repo": "known", "ranked": ["a.py"]},
        {"repo": "unlisted", "ranked": ["b.py"]},
    ]
    out = fabrication_rate(results, {"known": ["a.py"]})
    assert out["instances_scored"] == 1
    assert out["instances_unlistable"] == 1


# ---- what counts as a distinct mutation ----------------------------------------------


def test_a_mutation_that_unparses_to_the_original_is_not_counted():
    """Counting a no-op would inflate the false-accept rate with mutants that changed
    nothing observable - the number App 02 exists to report."""
    code = "def f(x):\n    return x + 1\n"
    produced = mutants(code)
    import ast

    original = ast.unparse(ast.parse(code))
    assert all(ast.unparse(ast.parse(m.code)) != original for m in produced)


def test_every_mutant_is_distinct():
    code = "def f(a, b):\n    if a > b:\n        return a - b\n    return a + b\n"
    produced = mutants(code)
    assert len(produced) >= 3
    assert len({m.code for m in produced}) == len(produced)


def test_every_mutant_still_parses():
    """A mutant that does not parse scores as `error`, which is not a tested failure -
    so a generator emitting them would quietly change what the kill rate measures."""
    import ast

    code = "def f(xs):\n    total = 0\n    for x in xs:\n        total += x * 2\n    return total\n"
    for mutant in mutants(code):
        ast.parse(mutant.code)  # raises if it does not


def test_the_limit_is_respected():
    code = "def f(a, b, c):\n    return a + b - c * 2\n"
    assert len(mutants(code, limit=2)) == 2


def test_unparseable_source_yields_no_mutants_rather_than_raising():
    assert mutants("def f(:\n") == []


def test_each_mutant_says_where_it_came_from():
    """A survivor is only useful if you can see what change survived."""
    for mutant in mutants("def f(a, b):\n    return a + b\n"):
        assert mutant.kind
        assert mutant.where.startswith(mutant.kind)
