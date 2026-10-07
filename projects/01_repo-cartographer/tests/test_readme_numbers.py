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
    """If the two columns ever converge, the README's argument has gone stale.

    The exact pair for every row is asserted by
    `test_each_documented_rate_is_the_one_the_code_measures` above - when the checkout
    is present. This ran `repo_pct > all_pct * 2`, a floor, in a file where the
    equality is already available, and it would be satisfied by a great many pairs the
    README does not state. It now asserts the gap each row actually shows, which is
    checkable from the README alone and so holds on a fresh clone where the rows skip.
    """
    rows = _rows()
    assert rows, "the comparison table no longer parses"
    for name, all_pct, repo_pct in rows:
        assert repo_pct > all_pct, f"{name}: {all_pct}% vs {repo_pct}%"
        # The narrowest gap in the published table, which is the claim a reader takes
        # from it: the in-scope rate is never merely a little higher.
        assert repo_pct - all_pct >= 50, f"{name}: {repo_pct}% - {all_pct}%"
    narrowest = min(repo - every for _, every, repo in rows)
    widest = max(repo - every for _, every, repo in rows)
    assert (narrowest, widest) == (55, 73), (narrowest, widest)


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

    The two reasons a map is not comparable are different and were counted as one.
    `assert comparable >= 1` is unsatisfiable on a fresh clone, where `REPOS_ROOT` holds
    no checkouts at all - so this test failed in exactly the configuration CI runs, and
    the failure said "regenerate them" about artifacts that were perfectly current. It
    was found by sweeping the tree with `REPOS_ROOT` pointed at an empty directory,
    which is the only way to see what a reader sees.

    Present-but-moved still fails, because that is the case the test is for.
    """
    import json

    present, comparable = 0, 0
    for stored in UI_DATA:
        root = REPOS_ROOT / stored.stem
        if not root.exists():
            continue
        present += 1
        held = json.loads(stored.read_text(encoding="utf-8"))
        if held.get("at_commit") == _head_commit(root):
            comparable += 1

    print(
        f"{comparable} of {present} present checkouts are at the recorded revision "
        f"({len(UI_DATA)} maps shipped)"
    )
    if not present:
        pytest.skip(f"no checkouts under {REPOS_ROOT}; nothing to compare against")
    assert comparable >= 1, (
        f"{present} of the five checkouts are here and none is at the revision its map "
        "records; regenerate them"
    )


# -- the badges, and the table they are supposed to agree with ---------------------


def test_the_resolution_badges_match_the_table_below_them():
    """Two rates in the header, repeated in the folder table, checked by nothing.

    An independent review found four of that table's eight rows already wrong on the
    day it was dated - every absolute count had moved, because several of those
    repositories are worked on daily. The rates had not, which is why they are what
    the table now leads with and the counts are given as magnitudes.

    These badges are the first thing on the page and were outside every check here.
    They cannot be recomputed without the sibling checkouts, so what is asserted is
    that they agree with the table in the same file - a disagreement between two
    numbers on one page is the failure that needs no external data to catch.
    """
    import re

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    badges = dict(re.findall(r"badge/(median|pooled)%20resolution-(\d+)%25", readme))
    assert set(badges) == {"median", "pooled"}, badges

    median = re.search(r"\*\*Median repo-call resolution\*\* \| \*\*(\d+)%\*\*", readme)
    pooled = re.search(r"\*\*Pooled over [^|]*\*\* \| \*\*(\d+)%\*\*", readme)
    assert median and pooled, "the folder table no longer states both rates"

    assert badges["median"] == median.group(1), (badges["median"], median.group(1))
    assert badges["pooled"] == pooled.group(1), (badges["pooled"], pooled.group(1))

    # The gap is the argument the section makes, so it has to survive both numbers
    # being updated together.
    assert int(median.group(1)) > int(pooled.group(1)), (median.group(1), pooled.group(1))


def test_the_folder_table_marks_which_rows_are_measurements():
    """The distinction the review's re-run established, kept in the table itself.

    A reader cannot tell a figure that is stable from one that moved overnight unless
    the table says so, and a count printed to the unit - "339,739 lines" - reads as
    the more precise of the two when it is the less durable.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    table = readme.split("## Measured across 78 repositories", 1)[1].split("\n\n")
    rows = [line for part in table for line in part.split("\n") if line.startswith("| ")]
    assert rows, "the folder table is gone"

    marked = [r for r in rows if r.rstrip().endswith(("| stable |", "| the measurement |"))]
    moving = [r for r in rows if "moves" in r.rsplit("|", 2)[-2]]
    assert len(marked) >= 6, rows
    assert len(moving) >= 3, rows

    # And no absolute count is printed to the unit any more, because that was the
    # form that went stale.
    for row in rows:
        assert "339,739" not in row and "32,527" not in row and "1,740" not in row, row


def test_the_headline_does_not_print_a_count_the_table_refuses_to():
    """The guard above covers the table, and the headline carried the same figures.

    "1,740 modules, 339,739 lines" stood four sections higher for as long as the
    table did without them: a rule applied to the place the finding named rather
    than to the claim it was about. The two figures survive on the page only in the
    paragraph that exists to say they moved.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    headline = readme.split("## Results", 1)[1].split("## ", 1)[0]
    for stale in ("339,739", "1,740", "32,527"):
        assert stale not in headline, f"{stale} is back in the headline"

    drift = readme.split("**The rates are the measurement", 1)[1].split("\n\n##", 1)[0]
    for quoted in ("339,739", "1,740"):
        assert quoted in drift, f"{quoted} left the paragraph that explains it"
