"""The README's two-column table against what the shipped code measures.

Every row of it was wrong once. The table claimed 99% and 100% repo-internal
resolution, which was the number the old denominator produced: method calls whose
receiver type an AST cannot infer were dropped from the denominator instead of
counted as unresolved. After the fix the same repositories measure 75-93%, and
nothing in the repository would have noticed the table still said otherwise.

So the table is recomputed here rather than trusted. A row whose checkout is not on
this machine is skipped by name, so the number of rows actually compared is printed
rather than assumed.
"""

import os
import re
from pathlib import Path

import pytest

from cartographer.graph import build_graph
from cartographer.parse import parse_repo
from cartographer.report import _head_commit

README = Path(__file__).resolve().parents[1] / "README.md"
REPOS_ROOT = Path(os.environ.get("REPOS_ROOT") or Path(__file__).resolve().parents[3].parent)

_ROW = re.compile(r"^\| ([a-z0-9][\w.-]*) \| (\d+)% \| \*\*(\d+)%\*\* \|$", re.MULTILINE)


def _rows() -> list[tuple[str, int, int]]:
    rows = [
        (m[1], int(m[2]), int(m[3])) for m in _ROW.finditer(README.read_text(encoding="utf-8"))
    ]
    assert rows, "the README's comparison table no longer parses"
    return rows


def test_the_table_has_the_five_rows_it_always_had():
    assert [name for name, _, _ in _rows()] == [
        "machine-learning",
        "mcp-lab",
        "rag-forge",
        "credit-risk-engine",
        "langchain-lab",
    ]


@pytest.mark.parametrize("name,all_pct,repo_pct", _rows(), ids=[r[0] for r in _rows()])
def test_each_documented_rate_is_the_one_the_code_measures(name, all_pct, repo_pct):
    root = REPOS_ROOT / name
    if not root.exists():
        pytest.skip(f"no checkout at {root}")
    resolution = build_graph(parse_repo(root)).resolution
    assert round(resolution.resolution_rate * 100) == all_pct
    assert round(resolution.repo_resolution_rate * 100) == repo_pct


def test_the_gap_between_the_columns_is_the_point():
    """If the two columns ever converge, the README's argument has gone stale."""
    for name, all_pct, repo_pct in _rows():
        assert repo_pct > all_pct * 2, f"{name}: {all_pct}% vs {repo_pct}%"


UI_DATA = sorted(
    (Path(__file__).resolve().parents[1] / "ui" / "public" / "data").glob("*.json")
)


def test_the_ui_ships_data_for_several_repositories():
    assert len(UI_DATA) == 5


@pytest.mark.parametrize("stored", UI_DATA, ids=[p.stem for p in UI_DATA])
def test_each_shipped_ui_map_is_what_the_code_now_produces(stored):
    """These are committed files that the UI renders as measurements.

    All five held the pre-fix rates - one of them 100% - for as long as the fix had
    been in, because nothing compared a committed artifact against the code that
    wrote it. The UI was showing numbers the tool no longer produces.

    The comparison is gated on the revision the map records. Written without that
    gate, this test began failing on `urdu-nlp-toolkit` within the hour, because
    somebody else had committed to that repository: a true statement about the world
    and a useless test. A map with no revision beside it cannot be checked against
    anything later, so `map` records one, and a moved checkout declines by name
    rather than failing or passing quietly.
    """
    import json

    root = REPOS_ROOT / stored.stem
    if not root.exists():
        pytest.skip(f"no checkout at {root}")
    held = json.loads(stored.read_text(encoding="utf-8"))

    recorded = held.get("at_commit", "")
    assert recorded, f"{stored.name} records no revision; regenerate it with `map --json`"
    now = _head_commit(root)
    if now != recorded:
        pytest.skip(
            f"{stored.stem} has moved since this map was taken "
            f"({recorded[:10]} -> {now[:10] or 'unknown'}); regenerate it to compare again"
        )

    fresh = build_graph(parse_repo(root)).resolution
    assert held["repo_resolution_rate"] == pytest.approx(fresh.repo_resolution_rate, abs=5e-5)
    assert held["resolution_rate"] == pytest.approx(fresh.resolution_rate, abs=5e-5)


def test_every_shipped_map_records_the_revision_it_was_taken_at():
    """Asserted separately, so a map with no revision fails rather than skipping.

    Otherwise the gate above could silently cover every artifact at once.
    """
    import json

    for stored in UI_DATA:
        held = json.loads(stored.read_text(encoding="utf-8"))
        assert held.get("at_commit"), f"{stored.name} has no at_commit"
        assert len(held["at_commit"]) == 40, held["at_commit"]


def test_the_maps_still_compared_are_counted():
    """How many of the five are actually being checked, printed and asserted non-zero.

    A per-artifact skip is honest; five of them silently is this file passing while
    checking nothing.
    """
    import json

    comparable = 0
    for stored in UI_DATA:
        root = REPOS_ROOT / stored.stem
        if not root.exists():
            continue
        held = json.loads(stored.read_text(encoding="utf-8"))
        if held.get("at_commit") == _head_commit(root):
            comparable += 1
    print(f"{comparable} of {len(UI_DATA)} shipped maps are at the recorded revision")
    assert comparable >= 1, "no shipped map is still comparable; regenerate them"
