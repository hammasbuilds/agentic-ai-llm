"""graph-clinic against HotpotQA, from the local HuggingFace cache.

All 7,405 validation questions, each with two gold paragraphs hidden among ten,
and each labelled ``bridge`` or ``comparison``. The graph is built from real
title mentions between paragraphs, not invented.

Every figure asserted here was produced by running this code over that cache.
"""

from pathlib import Path

import pytest

from graphclinic.hotpot import (
    baseline_hits_both,
    connected,
    lexical_top2,
    load,
    mentions,
)

try:
    ITEMS = load()
except Exception:  # noqa: BLE001 — absence is the skip condition
    ITEMS = ()

pytestmark = pytest.mark.skipif(not ITEMS, reason="HotpotQA not in the local HF cache")


def subset(kind=None):
    return [i for i in ITEMS if i.gold_present and kind in (None, i.kind)]


def rate(items, fn):
    return sum(1 for i in items if fn(i)) / len(items)


def test_the_whole_validation_split_loads_from_cache():
    assert len(ITEMS) == 7_405
    assert all(i.gold_present for i in ITEMS)
    assert {i.kind for i in ITEMS} == {"bridge", "comparison"}


def test_the_graph_is_built_from_real_mentions():
    item = next(i for i in ITEMS if mentions(i))
    a, b = next(iter(mentions(item)))
    assert b.lower() in item.paragraphs[a].lower()


def test_the_graph_is_four_times_the_baseline_on_bridge_questions():
    # THE FINDING, first half. A bridge question is one where you must hop from
    # one paragraph to another; a mention edge is exactly that hop, and it finds
    # it three quarters of the time against a baseline that manages a sixth.
    bridge = subset("bridge")
    assert len(bridge) == 5_918
    assert rate(bridge, lambda i: connected(i, 1)) == pytest.approx(0.753, abs=0.01)
    assert rate(bridge, baseline_hits_both) == pytest.approx(0.167, abs=0.01)


def test_and_it_is_useless_on_comparison_questions():
    # THE FINDING, second half. "Were Scott Derrickson and Ed Wood of the same
    # nationality?" needs two unrelated pages. There is no edge to traverse
    # because there is no relationship — the question is not about one.
    comparison = subset("comparison")
    assert len(comparison) == 1_487
    assert rate(comparison, lambda i: connected(i, 2)) < 0.02
    assert rate(comparison, baseline_hits_both) > rate(comparison, lambda i: connected(i, 2))


def test_one_hop_finds_almost_no_comparison_pair_at_all():
    # A tenth of a per cent. Not "weaker" — absent. The structure the graph
    # traverses is not the structure these questions are asking about.
    assert rate(subset("comparison"), lambda i: connected(i, 1)) < 0.005


def test_the_headline_number_hides_the_whole_result():
    # 62% against 15% reads as "the graph wins, use it everywhere", which would
    # be the wrong decision for the fifth of questions that are comparisons.
    everything = subset()
    assert rate(everything, lambda i: connected(i, 2)) == pytest.approx(0.615, abs=0.01)
    assert rate(everything, baseline_hits_both) == pytest.approx(0.151, abs=0.01)


def test_the_second_hop_buys_almost_nothing():
    bridge = subset("bridge")
    one = rate(bridge, lambda i: connected(i, 1))
    two = rate(bridge, lambda i: connected(i, 2))
    assert two - one < 0.02  # the value is in the direct mention


def test_the_sample_and_the_whole_split_agree_here():
    # Measured first on 3,000 questions: bridge 0.734, overall 0.600. On all
    # 7,405: 0.753 and 0.602. Recorded as a contrast with comms-desk, where the
    # same shortcut moved the answer by 25 points. Sampling is safe when the
    # measurement is a per-item rate, and unsafe when it is a collision count
    # over the whole pool — the pool is what a sample shrinks.
    bridge = rate(subset("bridge"), lambda i: connected(i, 1))
    assert abs(bridge - 0.734) < 0.03


def test_more_hops_never_finds_less():
    # Replaces a test that asserted `connected(i, 1) or not connected(i, 1)`,
    # which is true of everything and checked nothing. Reachability must be
    # monotonic in hop count, and zero hops must reach nothing.
    sample = subset("bridge")[:300]
    for item in sample:
        assert not connected(item, 0)
        assert connected(item, 1) <= connected(item, 2) <= connected(item, 3)


def test_the_baseline_returns_two_paragraphs():
    assert len(lexical_top2(ITEMS[0])) == 2


def test_a_missing_cache_is_reported_rather_than_faked(monkeypatch, tmp_path):
    """This raised the exception itself and caught it.

        with pytest.raises(DatasetMissingError):
            raise DatasetMissingError("shape of the failure when the cache is absent")

    There is no code under test in those two lines: `pytest.raises` was handed the
    thing it was asserting. Deleting the whole `if not found: raise` branch from
    `hotpot.py` left this green.

    The cache is pointed at an empty directory instead, which is also how
    `scripts/test_all.py --fresh` runs it.
    """
    from graphclinic import hotpot

    assert hotpot._validation_file().exists()

    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path))
    monkeypatch.setattr(hotpot, "CACHE", hotpot._datasets_cache() / "hotpotqa___hotpot_qa")
    with pytest.raises(hotpot.DatasetMissingError) as raised:
        hotpot._validation_file()
    # The message has to name where it looked, or the reader cannot tell a missing
    # dataset from a misconfigured path.
    assert str(tmp_path) in str(raised.value)
    assert "never downloaded here" in str(raised.value)


def test_the_cache_follows_the_environment_not_the_home_directory(monkeypatch, tmp_path):
    """`CACHE` was `Path.home() / ".cache/huggingface/datasets/..."`, a module constant.

    So all 28 tests here ran inside `scripts/test_all.py --fresh`, which had pointed
    `HF_HOME` at an empty directory precisely to find out what a reader without the
    data gets. An override replaces the default; it does not add to it.
    """
    from graphclinic import hotpot

    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path / "explicit"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))
    assert hotpot._datasets_cache() == tmp_path / "explicit"

    monkeypatch.delenv("HF_DATASETS_CACHE")
    assert hotpot._datasets_cache() == tmp_path / "home" / "datasets"

    monkeypatch.delenv("HF_HOME")
    assert hotpot._datasets_cache() == Path.home() / ".cache" / "huggingface" / "datasets"
