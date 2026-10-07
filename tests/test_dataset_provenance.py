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
import hashlib
import subprocess
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


def _all_paths() -> list[str]:
    """Every path in every committed listing, occurrences and not a set.

    Occurrences, because the figures quoted about these listings are about how often
    a shape turns up across them, and three Django listings holding the same file is
    three chances for a parser to meet it.
    """
    out: list[str] = []
    for path in sorted((DATA / "trees").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            out.extend(json.load(handle)["paths"])
    return out


#: What a comment says about these listings, how to count it, and the sentence that
#: says it. Each is a figure the path parser's design is argued from, written into a
#: comment where nothing could check it: `apps/_engine/locate_prompts.py` said "9 of
#: the 66,895 paths in `data/trees` are dot-prefixed Python files" and the number is
#: 14 occurrences of 5 distinct files. Every other figure in the same two comments was
#: right, which is the point - one of them was wrong and reading could not tell which.
#:
#: The sentence is part of the table because a figure corrected here and left wrong
#: where it is argued from is the same defect with a passing test over it. It is
#: matched as a phrase rather than as a bare number: "5" occurs in these files for
#: dozens of unrelated reasons, so `str(n) in source` would be an assertion that
#: cannot fail.
QUOTED_FIGURES = {
    "total paths": (
        lambda ps: len(ps),
        66_895,
        "`.py` is 35,339 of 66,895 paths",
    ),
    "`.py` paths": (
        lambda ps: sum(p.endswith(".py") for p in ps),
        35_339,
        "`.py` is 35,339 of 66,895 paths",
    ),
    "dot-prefixed paths": (
        lambda ps: sum(p.startswith(".") for p in ps),
        463,
        "463 of the 66,895 paths in",
    ),
    "dot-prefixed `.py` paths": (
        lambda ps: sum(p.startswith(".") and p.endswith(".py") for p in ps),
        14,
        "14 of the 66,895 paths in `data/trees` are dot-prefixed Python",
    ),
    "distinct dot-prefixed `.py` paths": (
        lambda ps: len({p for p in ps if p.startswith(".") and p.endswith(".py")}),
        5,
        "5 distinct ones",
    ),
    "`.rst` paths": (
        lambda ps: sum(p.endswith(".rst") for p in ps),
        6_002,
        "`.rst` is 6,002 paths",
    ),
    "`.po` paths": (
        lambda ps: sum(p.endswith(".po") for p in ps),
        3_646,
        "`.po` 3,646",
    ),
}

#: The two files whose comments argue from the figures above.
FIGURE_SOURCES = ("apps/_engine/locate_prompts.py", "tests/test_localize_eval.py")


@pytest.mark.parametrize("what", sorted(QUOTED_FIGURES))
def test_a_figure_quoted_about_the_listings_is_the_figure_in_them(what):
    count, stated, _sentence = QUOTED_FIGURES[what]
    assert count(_all_paths()) == stated, what


@pytest.mark.parametrize("what", sorted(QUOTED_FIGURES))
def test_the_sentence_that_argues_from_the_figure_still_says_it(what):
    _count, _stated, sentence = QUOTED_FIGURES[what]
    sources = "".join((ROOT / rel).read_text(encoding="utf-8") for rel in FIGURE_SOURCES)
    assert sentence in sources, f"{what}: no comment says {sentence!r} any more"


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


# -- the bytes, not just the note ------------------------------------------------------
#
# Everything above checks that the committed data is DESCRIBED: a note per directory, a
# licence per slice, counts that match the listings. Nothing checked that the data is the
# data. A reviewer replaced every label in `devign_test.parquet` and no test in this
# repository noticed - the one figure the README offers as model-free was being computed
# from a summary JSON rather than from the file, and the file had no digest either.
#
# The figure is derived from the labels now (see
# `tests/test_documented_rates.py::test_the_devign_baseline_is_derived_from_the_committed_split`),
# which closes the half that matters most: a changed file changes the number. This closes
# the other half, so a changed file is also a failure in its own right rather than a
# quietly different measurement.

DATA_DIGEST = Path(__file__).resolve().parent / "fixtures" / "data_digest.json"


def _digest() -> dict:
    return json.loads(DATA_DIGEST.read_text(encoding="utf-8"))


def test_every_committed_data_file_is_digested():
    """The manifest covers the tree rather than a chosen part of it.

    Derived from `git ls-files`, so a new slice that nobody adds to the manifest fails
    here instead of being silently undigested - which is the failure mode a hand-written
    manifest has.
    """
    tracked = {
        line
        for line in subprocess.run(
            ["git", "ls-files", "data/"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        if not line.endswith(".md")
    }
    assert tracked, "git ls-files data/ returned nothing; this test is measuring nothing"
    assert set(_digest()) == tracked, {
        "missing from the manifest": sorted(tracked - set(_digest())),
        "in the manifest and not tracked": sorted(set(_digest()) - tracked),
    }


@pytest.mark.parametrize("relative", sorted(_digest()))
def test_each_committed_data_file_is_the_file_that_was_measured(relative: str):
    path = ROOT / relative
    assert path.is_file(), relative
    recorded = _digest()[relative]
    assert path.stat().st_size == recorded["bytes"], (
        f"{relative} is {path.stat().st_size:,} bytes and the manifest says "
        f"{recorded['bytes']:,}"
    )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == recorded["sha256"], (
        f"{relative} is not the file every published figure over it was measured from. "
        "If the slice was deliberately replaced, re-measure the figures and rewrite "
        "tests/fixtures/data_digest.json; the numbers do not carry over."
    )


def test_the_benchmark_slices_are_all_present_and_not_empty():
    """A zero-byte stand-in passes a digest check only if the digest was taken of the
    stand-in, so the sizes are asserted as a floor as well."""
    digest = _digest()
    benchmarks = {k: v for k, v in digest.items() if k.startswith("data/benchmarks/")}
    assert len(benchmarks) >= 4, sorted(benchmarks)
    for relative, recorded in benchmarks.items():
        assert recorded["bytes"] > 10_000, (relative, recorded["bytes"])
