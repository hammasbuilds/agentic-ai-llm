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

#: `18.0% of 4,055 mutants`, `75.8% of everything` - a rate and the population it is
#: over, without a numerator. The numerator is what the two patterns above need and it
#: is not what this check uses: the question is whether `n` supports the decimals, and
#: `n` is right there. Added because the two above reached three pairs in the whole
#: repository, and the docstring above claims the category.
OVER = re.compile(r"(?P<pct>\d+\.\d+)%\s*(?:of|over|across)\s*(?:the\s*)?(?P<n>\d[\d,]{2,})")


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


def _rates_over_a_population() -> list[tuple[str, int, str, int]]:
    """`18.0% of 4,055 mutants` - a rate and its denominator, with no numerator.

    A separate population from `_pairs()`, because the two checks need different
    things: `k/n == pct` needs the numerator and "does n support that many decimals"
    does not. Feeding these to the first made `18.0% of 4,055` arrive as `0/4055` and
    fail for saying 18.0% of nothing.
    """
    found = []
    for doc in sorted(_markdown()):
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            for m in OVER.finditer(line):
                found.append(
                    (
                        doc.relative_to(ROOT).as_posix(),
                        lineno,
                        m.group("pct"),
                        int(m.group("n").replace(",", "")),
                    )
                )
    return found


def _every_rate() -> list[tuple[str, int, str]]:
    """Every percentage with a decimal, paired or not. The denominator of the coverage
    figure below, which is the thing a reader needs to judge this file by."""
    out = []
    for doc in sorted(_markdown()):
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            for m in re.finditer(r"\d+\.\d+%", line):
                out.append((doc.relative_to(ROOT).as_posix(), lineno, m.group(0)))
    return out


def test_there_are_rates_paired_with_their_fractions_to_check():
    """A sweep over nothing passes. Publishing the fraction beside the rate is the
    convention this file enforces, so there have to be some."""
    pairs = _pairs()
    assert len(pairs) >= 3, pairs


def test_how_much_of_the_published_rates_this_file_actually_reaches():
    """The coverage, stated rather than left to be computed.

    The check reads a percentage only where its denominator is beside it. That was
    three pairs against 190 decimal percentages in this repository's markdown - 1.6% -
    under a docstring claiming "no published rate", and under a floor of `>= 3` sitting
    exactly on the three it found. A reviewer measured it; the file should.

    Asserted as a share rather than a count, so adding prose cannot quietly dilute it,
    and printed in the failure message either way.
    """
    checkable = {(w, n) for w, n, _p, _k, _d in _pairs()} | {
        (w, n) for w, n, _p, _d in _rates_over_a_population()
    }
    every = _every_rate()
    assert every, "no decimal percentages at all, so this file is measuring nothing"
    share = len(checkable) / len(every)

    # The measured value, not a target. Four of 191 decimal percentages in this
    # repository's markdown carry the population they are over in the same breath, so
    # that is what this file can judge - and a reader comparing its docstring ("no
    # published rate carries more decimals than its own stated fraction supports")
    # against its reach deserves the number rather than the impression.
    #
    # Pinned so it cannot quietly fall, and asserted as a share so adding prose does
    # not dilute it unnoticed. It is low because most rates here are published in a
    # sentence that names the population somewhere else - which is a convention worth
    # changing, and changing it moves this figure up and this line with it.
    assert share >= 0.02, (
        f"{len(checkable)} of {len(every)} decimal percentages ({share:.1%}) are "
        "printed with the population they are over, which is all this file can check."
    )
    assert len(checkable) >= 4, sorted(checkable)


def test_no_rate_is_printed_to_more_decimals_than_its_sample_supports():
    """Over both populations: a rate with its fraction, and a rate with its denominator.

    The second is where most of this repository's rates live - `18.0% of 4,055 mutants`
    - and the check needs nothing else to judge them.
    """
    offenders = []
    both = [(w, n, p, 0, d) for w, n, p, d in _rates_over_a_population()] + _pairs()
    for where, lineno, pct, _k, n in both:
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
