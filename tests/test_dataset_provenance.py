"""Every committed data slice says where it came from and under what terms.

`data/benchmarks/` had a licence section naming all four of its sources.
`data/trees/` had no note at all: 34 file listings from twelve repositories, 460 KB,
with nothing beside them saying which repositories, at which commits, or under whose
licence - and one of those projects (`pylint`) is GPL where the rest are permissive.

What is committed there is a set of path names rather than anyone's source, which is
why it is redistributable at all, and that is the thing a note has to say plainly. A
reader who cannot tell which it is has to assume the stricter answer.

This checks the parts that can be checked: a note exists, every source named on disk
appears in it, and the counts it prints are the counts in the directory. The licence
column is a fact about an upstream project that no file here can produce, so it is
checked for presence and shape only.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

#: Licence identifiers a row may carry. A row with something else is a row somebody
#: typed a sentence into, which is the state this file is here to prevent.
LICENCE_SHAPE = re.compile(
    r"^(MIT|Apache-2\.0|BSD-2-Clause|BSD-3-Clause|CC-BY-4\.0|GPL-2\.0-or-later|"
    r"PSF-based \(matplotlib licence\))$"
)


def test_every_committed_data_directory_has_a_note():
    """A sweep over no directories passes, and both of these hold committed slices."""
    holding = sorted(
        d for d in DATA.iterdir() if d.is_dir() and any(p.is_file() for p in d.iterdir())
    )
    assert [d.name for d in holding] == ["benchmarks", "trees"], holding
    for directory in holding:
        note = directory / "README.md"
        assert note.is_file(), f"{directory.name} has no README"
        text = note.read_text(encoding="utf-8")
        assert "## Licence" in text or "## Licences" in text, directory.name


def _tree_rows() -> list[tuple[str, str, str, int]]:
    rows = []
    for path in sorted((DATA / "trees").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            listing = json.load(handle)
        rows.append(
            (listing["repo"], listing.get("ref", ""), listing.get("how", ""), len(listing["paths"]))
        )
    return rows


def _documented_trees() -> dict[str, tuple[int, int, str]]:
    """Repository -> (listings, paths, licence), from the table in the note."""
    text = (DATA / "trees" / "README.md").read_text(encoding="utf-8")
    out = {}
    for row in re.finditer(r"^\|\s*`([\w.-]+/[\w.-]+)`\s*\|(.+?)\|(.+?)\|(.+?)\|\s*$", text, re.M):
        repo, listings, paths, licence = row.groups()
        out[repo] = (
            int(listings.strip()),
            int(paths.strip().replace(",", "")),
            licence.strip(),
        )
    return out


def test_the_tree_note_lists_every_repository_on_disk():
    on_disk = {repo for repo, _ref, _how, _n in _tree_rows()}
    documented = _documented_trees()
    assert on_disk, "no tree listings found"
    assert set(documented) == on_disk, (
        f"documented and absent: {sorted(set(documented) - on_disk)}; "
        f"on disk and undocumented: {sorted(on_disk - set(documented))}"
    )


@pytest.mark.parametrize("repo", sorted({r for r, _, _, _ in _tree_rows()}))
def test_each_repositorys_counts_are_the_ones_on_disk(repo):
    """The counts are the reason the table is worth having: nine listings for
    `scikit-learn` is the statement that nine instances sit at nine commits, and
    resolving them against one listing would credit a retriever for naming a file that
    did not exist yet."""
    rows = [r for r in _tree_rows() if r[0] == repo]
    listings, paths, _licence = _documented_trees()[repo]
    assert listings == len(rows), f"{repo}: note says {listings} listing(s), found {len(rows)}"
    assert paths == sum(n for _, _, _, n in rows), f"{repo}: note says {paths:,} paths"


def test_every_licence_is_an_identifier_and_not_a_sentence():
    for repo, (_listings, _paths, licence) in sorted(_documented_trees().items()):
        assert LICENCE_SHAPE.match(licence), f"{repo}: {licence!r}"


def test_the_totals_in_the_prose_match_the_table():
    """ "34 listings, 66,895 paths" is a sentence a reader checks nothing against."""
    text = (DATA / "trees" / "README.md").read_text(encoding="utf-8")
    stated = re.search(r"(\d+) listings, ([\d,]+) paths", text)
    assert stated, "the note no longer states its totals"
    rows = _tree_rows()
    assert int(stated.group(1)) == len(rows)
    assert int(stated.group(2).replace(",", "")) == sum(n for _, _, _, n in rows)


def test_the_how_counts_are_the_ones_in_the_directory():
    """`how` distinguishes a GitHub trees API response from a local walk, and the API
    truncates a very large tree where a walk does not. A note that miscounts them is
    describing a different set of files."""
    text = (DATA / "trees" / "README.md").read_text(encoding="utf-8")
    counts = Counter(how for _repo, _ref, how, _n in _tree_rows())
    for how, number in sorted(counts.items()):
        assert f"`{how}` ({number})" in text, f"{how}: {number} on disk"


def test_the_benchmark_note_names_a_licence_for_every_slice():
    """It did already. Asserted so a fifth slice cannot arrive without one."""
    text = (DATA / "benchmarks" / "README.md").read_text(encoding="utf-8")
    licences = text.split("## Licences", 1)[-1]
    for slice_file in sorted((DATA / "benchmarks").iterdir()):
        if slice_file.suffix in (".md",):
            continue
        row = re.search(rf"`{re.escape(slice_file.name)}`\s*\|\s*`([^`]+)`", text)
        assert row, f"{slice_file.name} is not in the table"
        source = row.group(1).split("/")[-1].split(",")[0]
        family = source.split("_")[0].split("-")[0]
        assert family.lower() in licences.lower() or source.lower() in licences.lower(), (
            f"{slice_file.name} comes from {source} and no licence names it"
        )
