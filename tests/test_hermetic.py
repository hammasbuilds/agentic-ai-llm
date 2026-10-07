"""Whether this repository can measure anything on a machine that is not this one.

An independent review ran the suite with a faked `HOME` and got **11 failures, not
skips** — `tests/test_lost_generations.py` and `tests/test_platform_degraded.py` assert
the exception a runner raises when the model is unreachable, and without MBPP or Devign
cached the runner raised `FileNotFoundError` first, so the `isinstance` check failed.
`datasets` is in neither `pyproject.toml` nor `uv.lock`, so the download fallback could
not fire either. CI had never executed those files: the last green run predates the
commit that added them.

Underneath that was one defect in three copies. `datasets.py`, `swebench_data.py` and
`apps/03_vuln_baseline/app.py` each resolved the Hugging Face cache themselves, and all
three appended `~/.cache/huggingface/hub` *underneath* `HF_HOME` and `HF_HUB_CACHE`
rather than letting them replace it. The variables were extra search paths. Pointing one
at an empty directory isolated nothing, so every check of whether the suite ran offline
was reading the real cache — which is how a suite needing about 1.5 GB of downloads
passed as hermetic on the one machine that had them.

Both halves are fixed: `apps/_engine/hf_cache` is the single resolver and an override
replaces the default, and `data/benchmarks/` holds the columns these apps read, 2.8 MB,
committed beside `data/trees` which is committed for the same reason.

So this file asserts the thing the README claims: with the cache pointed at an empty
directory, the datasets still load and the flagship measurement still reproduces.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps._engine import hf_cache  # noqa: E402

NEEDED = ("swebench_lite_test.parquet", "devign_test.parquet", "mbpp.jsonl", "sanitized-mbpp.json")


@pytest.fixture
def empty_cache(tmp_path, monkeypatch):
    """Both override variables pointed at an empty directory."""
    blank = tmp_path / "no-hf-cache"
    blank.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(blank))
    monkeypatch.setenv("HF_HOME", str(blank))
    return blank


# -- the override is an override --------------------------------------------


def test_an_override_replaces_the_default_rather_than_adding_to_it(empty_cache):
    roots = hf_cache.cache_roots()
    assert roots == [empty_cache], roots
    assert Path.home() / ".cache" / "huggingface" / "hub" not in roots


def test_hf_home_is_honoured_when_hf_hub_cache_is_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert hf_cache.cache_roots() == [tmp_path / "hub"]


def test_with_neither_set_it_is_the_documented_default(monkeypatch):
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    assert hf_cache.cache_roots() == [Path.home() / ".cache" / "huggingface" / "hub"]


def test_there_is_exactly_one_cache_resolver_in_the_repository():
    """There were three, and all three had the same bug.

    Walks the tree rather than using `git grep`, which searches only tracked files -
    so the first version of this test passed while a new untracked resolver sat
    beside it. A checker that cannot see the thing it looks for.
    """
    hits = sorted(
        str(found.relative_to(ROOT)).replace(chr(92), "/")
        for folder in ("apps", "tests")
        for found in (ROOT / folder).rglob("*.py")
        if "__pycache__" not in found.parts
        and ".cache/huggingface/hub" in found.read_text(encoding="utf-8", errors="replace")
    )
    assert hits == [
        "apps/_engine/hf_cache.py",
        "tests/test_hermetic.py",
    ], f"a second cache resolver is back: {hits}"


# -- the committed slices ---------------------------------------------------


def test_every_slice_the_apps_read_is_committed():
    missing = [name for name in NEEDED if hf_cache.committed(name) is None]
    assert missing == [], f"not committed: {missing}"


def test_the_slices_are_small_enough_to_belong_in_git():
    total = sum(hf_cache.committed(name).stat().st_size for name in NEEDED)
    assert total < 8_000_000, f"{total / 1e6:.1f} MB of benchmark data is too much for git"
    assert total > 1_000_000, "the slices look truncated"


@pytest.mark.parametrize("benchmark,expected", [("mbpp", 972), ("mbpp-sanitized", 413)])
def test_the_code_benchmarks_load_with_no_cache_at_all(empty_cache, benchmark, expected):
    from apps._engine.datasets import load

    assert len(load(benchmark)) == expected


#: Rows on disk against rows a loader can use. `data/benchmarks/README.md` said this
#: module "asserts the row counts (300 / 2,732 / 972 / 413)" and it asserted
#: `len(load(...))` for two of the four - the post-filter count - while the other two
#: really were row counts. Both numbers now, named as what they are.
MBPP_POPULATION = {"full": (974, 972, 2), "sanitized": (427, 413, 14)}


@pytest.mark.parametrize("split", sorted(MBPP_POPULATION))
def test_the_mbpp_slices_row_counts_and_usable_counts_are_both_what_is_published(
    empty_cache, split
):
    """The distinction the provenance table was collapsing.

    `load_mbpp` skips any row whose tests never call a function it can name as the
    entry point, which is correct - there is nothing to run a reference against - and
    it did it with a bare `continue`. So every rate the apps publish is over `usable`,
    the table printed `usable` as though it were the file's size, and nothing anywhere
    compared either number to the file.
    """
    from apps._engine import hf_cache
    from apps._engine.datasets import mbpp_population

    rows, usable, dropped = MBPP_POPULATION[split]
    population = mbpp_population(split)
    assert (population.rows, population.usable, population.dropped) == (rows, usable, dropped)

    # Against the file itself, not against the loader: the point is that the two can
    # differ, so one of them has to be measured without going through the loader.
    name = "mbpp.jsonl" if split == "full" else "sanitized-mbpp.json"
    path = hf_cache.committed(name)
    text = path.read_text(encoding="utf-8")
    if split == "full":
        on_disk = len([line for line in text.splitlines() if line.strip()])
    else:
        import json

        on_disk = len(json.loads(text))
    assert on_disk == rows, f"{name} holds {on_disk} rows; the table says {rows}"


@pytest.mark.parametrize("split", sorted(MBPP_POPULATION))
def test_the_discarded_rows_are_named_and_are_the_ones_with_no_entry_point(empty_cache, split):
    """A count alone is satisfied by discarding something else.

    Each id is checked against the reason: no test in that row calls a function by
    name, so there is nothing for the entry-point regex to find. That is the only
    exclusion this loader is allowed to make.
    """
    import json

    from apps._engine import hf_cache
    from apps._engine.datasets import _CALLED, mbpp_population

    population = mbpp_population(split)
    assert population.discarded, split
    assert len(set(population.discarded)) == population.dropped, "a duplicate id"

    name = "mbpp.jsonl" if split == "full" else "sanitized-mbpp.json"
    text = hf_cache.committed(name).read_text(encoding="utf-8")
    if split == "full":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        rows = json.loads(text)

    by_id = {f"mbpp/{row['task_id']}": row for row in rows}
    for task_id in population.discarded:
        row = by_id[task_id]
        assert not any(_CALLED.search(t) for t in row["test_list"]), (
            f"{task_id} was discarded and its tests do name a function"
        )


def test_the_provenance_table_states_both_numbers():
    """The table is where the two were conflated, so the table is what is checked."""
    note = (ROOT / "data" / "benchmarks" / "README.md").read_text(encoding="utf-8")
    for split, (rows, usable, dropped) in sorted(MBPP_POPULATION.items()):
        del split
        assert f"**{rows} rows**, {usable} usable" in note, (rows, usable)
        assert f"| {rows} | {usable} | " in note, f"the rows/usable table is missing {rows}"
        del dropped


def test_swebench_lite_loads_with_no_cache_at_all(empty_cache):
    from apps._engine.swebench_data import find_parquet, load

    found = find_parquet()
    assert found is not None and found.name == "swebench_lite_test.parquet"
    instances = load()
    assert len(instances) == 300
    assert all(i.gold_files for i in instances), "the patch column did not survive slicing"


def test_devign_loads_with_no_cache_at_all(empty_cache):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vuln_baseline", ROOT / "apps" / "03_vuln_baseline" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    frame = module._load_devign("test")
    assert len(frame) == 2732
    safe = int((~frame["target"].astype(bool)).sum())
    assert safe == 1477, "the always-SAFE baseline the README quotes comes from this"


# -- the claim the README makes ---------------------------------------------


def test_the_flagship_measurement_reproduces_with_no_cache_and_no_network(empty_cache):
    """README: "the BM25 row ... is reproducible with no model and no network".

    It raised `FileNotFoundError` on a fresh clone, and the four tests that verify it
    skipped in exactly that condition - so the one claim the repository offered as
    checkable by a stranger was checkable only here.
    """
    from apps._engine import localize_eval

    out = localize_eval.run()
    tiers = out["recall"]["bm25"]["by_tier"]

    assert out["population"]["scored"] == 300
    # Fractions, not rates to one decimal: 51 instances do not support the decimal
    # place, and the same headline was written as both 8.4% and 8.5% elsewhere.
    assert (tiers["full_path"]["hits@10"], tiers["full_path"]["n"]) == (38, 51)
    assert (tiers["not_mentioned"]["hits@10"], tiers["not_mentioned"]["n"]) == (13, 154)


def test_the_readme_does_not_promise_a_download(empty_cache):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m apps._engine.localize_eval" in readme
    assert "data/benchmarks" in readme, (
        "the README says the measurement runs offline; it has to say where the data is"
    )


def test_no_module_in_this_suite_reads_the_cache_at_import_time():
    """The guarantee, over the thing that can actually be checked from inside.

    This asserted

        os.environ.get("HF_HUB_CACHE") is None or Path(os.environ["HF_HUB_CACHE"]).exists()

    which is true in every intended configuration: unset, or set to a directory that
    was created before the run. Its docstring said the count was "printed rather than
    asserted" and nothing was printed. Deleting `data/benchmarks` entirely left it
    green.

    What a test inside the suite CAN establish is that collection does not touch the
    cache: every module here imports and is collected with the cache pointed at an
    empty directory, so a module-level `load()` or a path resolved at import fails here
    rather than two hundred tests later. The run-time half is the sweep's job -
    `scripts/test_all.py --write-counts` runs every suite with the cache emptied and
    refuses to record a red one.
    """
    import subprocess

    empty = Path(tempfile.mkdtemp(prefix="hermetic-collect-"))
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(ROOT),
        env={
            **os.environ,
            "HF_HOME": str(empty),
            "HF_HUB_CACHE": str(empty),
            "HF_DATASETS_CACHE": str(empty),
        },
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert done.returncode == 0, (
        "collecting this suite with the HuggingFace cache pointed at an empty directory "
        "failed, so something reads it at import time: " + (done.stdout + done.stderr)[-1200:]
    )
    found = re.search(r"(\d+) tests? collected", done.stdout)
    assert found, done.stdout[-500:]
    # The same number either way: a module that skipped itself at import would collect
    # fewer, and that is a silent loss rather than a failure.
    here = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    mine = re.search(r"(\d+) tests? collected", here.stdout)
    assert mine, here.stdout[-500:]
    assert found.group(1) == mine.group(1), (
        f"collection differs: {found.group(1)} with an empty cache, {mine.group(1)} with "
        "the real one. A module is deciding at import time whether its tests exist."
    )
