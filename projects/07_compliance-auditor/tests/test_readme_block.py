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
