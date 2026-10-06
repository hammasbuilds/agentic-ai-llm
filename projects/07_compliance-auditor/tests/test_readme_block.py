"""The README's audit block, checked for internal consistency.

Re-auditing 78 checkouts here would take minutes and depend on what happens to be
on the machine, so this does not re-measure. It does something cheaper that would
have caught every drift this block has had: the figures in it have to add up.

The block used to read "37 repositories - 248/340 controls passed (73%)" with ten
controls, and 37 x 10 is 370, not 340 - because seven of the repositories held no
Python and three no README, so some controls never ran on them. That is fine, and
it is exactly why the pass rate must be read against the measured denominator
rather than the repository count. What is not fine is the four headline numbers
drifting apart, which is what these assertions pin.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from auditor.controls import CONTROLS

README = Path(__file__).resolve().parents[1] / "README.md"
TEXT = README.read_text(encoding="utf-8")

HEADLINE = re.compile(r"(\d+) repositories\s+-\s+(\d+)/(\d+) controls passed \((\d+)%\)")
TALLY = re.compile(r"pass (\d+)\s+fail (\d+)\s+inconclusive (\d+)\s+n/a (\d+)")
ROW = re.compile(r"^\s+(\d+)/(\d+)\s+(\d+)%\s+([a-z-]+)$", re.MULTILINE)


def test_the_headline_rate_is_the_headline_fraction():
    repos, passed, measured, pct = (int(g) for g in HEADLINE.search(TEXT).groups())
    assert repos > 0
    assert round(passed / measured * 100) == pct


def test_the_tally_accounts_for_every_control_run():
    repos, passed, measured, _ = (int(g) for g in HEADLINE.search(TEXT).groups())
    p, f, inc, na = (int(g) for g in TALLY.search(TEXT).groups())
    assert p == passed
    assert p + f == measured, "the rate's denominator is pass + fail, nothing else"
    assert p + f + inc + na == repos * len(CONTROLS), (
        "every control on every repository must land in exactly one bucket"
    )


def test_every_per_control_row_is_its_own_fraction():
    rows = ROW.findall(TEXT)
    assert len(rows) == len(CONTROLS), f"{len(rows)} rows for {len(CONTROLS)} controls"
    for passed, measured, pct, name in rows:
        assert round(int(passed) / int(measured) * 100) == int(pct), name


def test_the_per_control_rows_sum_to_the_headline():
    _, passed, measured, _ = (int(g) for g in HEADLINE.search(TEXT).groups())
    rows = ROW.findall(TEXT)
    assert sum(int(r[0]) for r in rows) == passed
    assert sum(int(r[1]) for r in rows) == measured


def test_every_control_in_the_code_appears_in_the_block():
    named = {r[3] for r in ROW.findall(TEXT)}
    assert named == {c.id for c in CONTROLS}


def test_the_headline_claim_matches_its_own_row():
    """The sentence above the block quotes readme-limits. It must quote this run."""
    claim = re.search(r"holds in \*\*(\d+) of (\d+)\*\* — \*\*(\d+)%\*\*", TEXT)
    assert claim, "the headline sentence no longer parses"
    row = next(r for r in ROW.findall(TEXT) if r[3] == "readme-limits")
    assert (claim[1], claim[2], claim[3]) == (row[0], row[1], row[2])


# -- the prose beside the block, which the block's tests never read -------


def _audit_counts() -> dict[str, int]:
    """Failing repositories per control, from the audit the README quotes."""
    import os
    from collections import Counter
    from pathlib import Path as _Path

    from auditor.controls import CONTROLS
    from auditor.evidence import collect

    root = _Path(os.environ.get("REPOS_ROOT") or _Path(__file__).resolve().parents[4])
    counts: Counter = Counter()
    seen = 0
    for repo in sorted(root.iterdir()):
        if not repo.is_dir() or repo.name.startswith("."):
            continue
        try:
            evidence = collect(repo)
        except Exception:  # noqa: BLE001 - a bad checkout is not this test's subject
            continue
        seen += 1
        for control in CONTROLS:
            if control.check(evidence).status == "fail":
                counts[control.id] += 1
    counts["_repositories"] = seen
    return dict(counts)


def test_the_prose_counts_are_the_audits_counts():
    """They were three to five times low, and the block's tests could not see it.

    `test_readme_block.py` parses only the fenced output, so "Four repositories import
    packages they never declare" sat beside a correct table while the audit found 20,
    and "Fourteen repositories declare dependencies nothing imports" while it found 41.
    The hand-written half of the Results section flattered the portfolio by a factor of
    three and forty-four green tests had nothing to say about it.
    """
    import re

    counts = _audit_counts()
    if counts["_repositories"] < 20:
        pytest.skip(f"only {counts['_repositories']} checkouts here; set REPOS_ROOT")

    imports = re.search(r"\*\*(\d+) repositories import packages they never declare\*\*", TEXT)
    declares = re.search(
        r"\*\*(\d+) repositories declare dependencies nothing imports\*\*", TEXT
    )
    assert imports and declares, "the Results prose no longer states these counts"

    assert int(imports.group(1)) == counts["imports-declared"]
    assert int(declares.group(1)) == counts["deps-used"]


def test_the_repositories_the_remote_claim_names_all_exist():
    """The old sentence named four that do not.

    "Four are not git repositories at all: `computer-vision`, `multimodal-emotion`,
    `infra` and `swe` hold real work on one disk with no copy anywhere." None of those
    four is on this disk. A sentence can outlive the thing it describes as well as
    miscount it, and the fenced block's tests could see neither.

    Scoped to that one sentence rather than to every backticked word in the section: a
    first version flagged `ast`, `tomllib`, `git` and three control ids, which is a
    heuristic failing in the direction that cries wolf.
    """
    import re
    from pathlib import Path as _Path

    sentence = re.search(r"\*\*\d+ of \d+ have no git remote\*\*:([^.]+)\.", TEXT)
    assert sentence, "the Results prose no longer states the remote count"

    named = re.findall(r"`([^`]+)`", sentence.group(1))
    assert named, "the claim names no repository"

    root = _Path("D:/github")
    if not root.is_dir():
        pytest.skip("the portfolio folder is not on this machine")
    missing = sorted(name for name in named if not (root / name).exists())
    assert missing == [], f"the remote claim names directories that do not exist: {missing}"

    # And the count matches how many it names.
    stated = int(re.search(r"\*\*(\d+) of \d+ have no git remote\*\*", TEXT).group(1))
    assert stated == len(named), f"says {stated}, names {len(named)}"


def test_the_badge_counts_the_repositories_the_block_does():
    import re

    badge = re.search(r"repos%20audited-(\d+)-", TEXT)
    assert badge, "the repos badge is gone"
    repos, _, _, _ = (int(g) for g in HEADLINE.search(TEXT).groups())
    assert int(badge.group(1)) == repos
