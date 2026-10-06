"""No published rate carries more decimals than its own stated fraction supports.

An independent review found the tier table printing a rate to one decimal on tiers as
small as 18 instances, where one instance is 5.6 percentage points - so the digit after
the point moved with nothing and was shown with the authority of a measurement.
`evaluate.summarize` now returns `hits@{k}` beside each `recall@{k}` and the table
prints the fraction, which is the fix: a reader who can see 13 of 154 does not have to
trust the 8.4%.

This is the check that keeps it true. One item moves a rate by `100/n` points, and a
percentage printed to `d` decimals claims a resolution of `10**-d` points, so the last
digit is spurious when one item is worth more than `10**(1-d)` of them:

    d=1 needs n >= 100       d=2 needs n >= 1,000       d=4 needs n >= 100,000

Only a percentage written immediately beside its own fraction is judged, so the
denominator is the document's own rather than one inferred from nearby prose. That is
deliberately narrow: the first version of this reached across a sentence and paired
"8.4%" with the "38 of 51" belonging to the figure before it, which is exactly the kind
of plausible-looking arithmetic the repository is about.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache"}

#: `8.4% (13 of 154)` and `13 of 154 (8.4%)`, with `/` accepted for `of`. The fraction
#: and the percentage have to be adjacent - one bracket apart, nothing else between.
AFTER = re.compile(r"(?P<pct>\d+\.\d+)%\s*\(\s*\*{0,2}(?P<k>\d[\d,]*)\s*(?:/|of)\s*(?P<n>\d[\d,]*)")
BEFORE = re.compile(
    r"(?P<k>\d[\d,]*)\s*(?:/|of)\s*(?P<n>\d[\d,]*)\s*\*{0,2}\)?\s*\(?\s*\*{0,2}(?P<pct>\d+\.\d+)%"
)


def _markdown() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not (SKIP_PARTS & set(p.parts))]


def _pairs() -> list[tuple[str, int, str, int, int]]:
    found = []
    for doc in sorted(_markdown()):
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            for pattern in (AFTER, BEFORE):
                for m in pattern.finditer(line):
                    n = int(m.group("n").replace(",", ""))
                    k = int(m.group("k").replace(",", ""))
                    pct = m.group("pct")
                    found.append((doc.relative_to(ROOT).as_posix(), lineno, pct, k, n))
    return found


def test_there_are_rates_paired_with_their_fractions_to_check():
    """A sweep over nothing passes. Publishing the fraction beside the rate is the
    convention this file enforces, so there have to be some."""
    pairs = _pairs()
    assert len(pairs) >= 3, pairs


def test_no_rate_is_printed_to_more_decimals_than_its_sample_supports():
    offenders = []
    for where, lineno, pct, _k, n in _pairs():
        decimals = len(pct.split(".")[1])
        if n and 100 / n > 10 ** (1 - decimals):
            offenders.append(
                f"{where}:{lineno} {pct}% over n={n}: one item is {100 / n:.2f} points, "
                f"{decimals} decimal(s) needs n >= {10 ** (decimals + 1):,}"
            )
    assert not offenders, offenders


def test_each_paired_rate_is_the_fraction_beside_it():
    """The other half of the convention, and the cheaper mistake to make: a fraction
    and a percentage that do not agree. Checked to the precision printed, so 13 of 154
    has to round to whatever decimals the percentage carries."""
    wrong = []
    for where, lineno, pct, k, n in _pairs():
        if not n:
            continue
        decimals = len(pct.split(".")[1])
        if f"{k / n * 100:.{decimals}f}" != pct:
            wrong.append(f"{where}:{lineno} says {pct}% for {k}/{n} ({k / n * 100:.4f}%)")
    assert not wrong, wrong
