"""Collapse log lines into templates, and measure what that collapsing destroys.

Template extraction is the standard first step in log analysis: a million
lines become a couple of hundred patterns and everything downstream becomes
tractable. `incident-copilot` already does that and groups the result into
incidents.

This module asks the other question. **Compression is achieved by deciding two
lines are the same. Sometimes they are not.** A threshold loose enough to give
a good compression ratio will merge distinct events, and the merged-away event
is disproportionately the rare one - which is the one you were looking for.

So every template carries the set of distinct raw messages that fell into it,
and the damage a threshold causes is reported next to the compression it buys.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

WILDCARD = "<*>"

# Ordered: the first pattern that matches a token wins.
_MASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"), "<TIME>"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "<DATE>"),
    (re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d+)?$"), "<TIME>"),
    (
        re.compile(r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I),
        "<UUID>",
    ),
    (re.compile(r"^[0-9a-f]{7,40}$", re.I), "<HASH>"),
    (re.compile(r"^\d+(?:\.\d+)?%$"), "<PCT>"),
    (re.compile(r"^[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?$", re.I), "<NUM>"),
    (re.compile(r"^(?:/|[A-Za-z]:\\)\S*$"), "<PATH>"),
    (re.compile(r"^\S+\.(?:py|js|ts|go|java|rs|log|json|csv|toml)$"), "<FILE>"),
    (re.compile(r"^https?://\S+$"), "<URL>"),
    (re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?$"), "<IP>"),
)


def mask(token: str) -> str:
    """Replace a token with a placeholder if it is clearly a variable."""
    for pattern, placeholder in _MASKS:
        if pattern.match(token):
            return placeholder
    return token


def tokenise(line: str) -> list[str]:
    return [mask(t) for t in line.strip().split()]


@dataclass
class Template:
    """A pattern, and every distinct message that was folded into it."""

    tokens: list[str]
    count: int = 0
    members: Counter = field(default_factory=Counter)
    first_line: int = 0

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

    @property
    def distinct_messages(self) -> int:
        """How many genuinely different lines this template represents.

        Distinct *after* masking variables, so `took 3ms` and `took 9ms` count
        once. Anything above one means the template merged messages that were
        not the same event.
        """
        return len(self.members)

    @property
    def merged(self) -> bool:
        return self.distinct_messages > 1

    @property
    def wildcards(self) -> int:
        return sum(1 for t in self.tokens if t == WILDCARD)

    def examples(self, n: int = 3) -> list[str]:
        return [m for m, _ in self.members.most_common(n)]


def _similarity(a: list[str], b: list[str]) -> float:
    """Share of positions holding the same token. Drain's sequence distance."""
    if len(a) != len(b) or not a:
        return 0.0
    same = sum(1 for x, y in zip(a, b, strict=False) if x == y)
    return same / len(a)


def _merge(tokens: list[str], other: list[str]) -> list[str]:
    return [x if x == y else WILDCARD for x, y in zip(tokens, other, strict=False)]


@dataclass
class Extraction:
    templates: list[Template]
    #: Lines that were scored - blank lines are skipped and are not in it.
    lines: int
    threshold: float
    #: Lines handed in, blanks included. `cli cost` printed this number under a
    #: header while every compression figure divided by `lines`, so one input gave
    #: two different corpus sizes - 1,005 and 973 - and the ratio in the table was
    #: not the ratio its own header implied.
    lines_read: int = 0

    @property
    def compression(self) -> float:
        """Lines per template, over the lines actually scored.

        The denominator is `lines`, not `lines_read`: a blank line is not an event
        and compressing it is not an achievement. `blank_lines` reports the gap so
        the two numbers can never be read as the same one again.
        """
        return self.lines / len(self.templates) if self.templates else 0.0

    @property
    def blank_lines(self) -> int:
        """Lines handed in and not scored, because they were blank."""
        return max(0, self.lines_read - self.lines)

    @property
    def merged_templates(self) -> list[Template]:
        return [t for t in self.templates if t.merged]

    @property
    def lines_in_merged(self) -> int:
        return sum(t.count for t in self.merged_templates)

    @property
    def distinct_messages_lost(self) -> int:
        """Distinct messages that no longer have a template of their own.

        This is the cost of compression, in the unit that matters: how many
        genuinely different things the reader can no longer tell apart.
        """
        return sum(t.distinct_messages - 1 for t in self.merged_templates)

    @property
    def singletons(self) -> list[Template]:
        """Templates seen once. The rare line is usually the interesting one."""
        return [t for t in self.templates if t.count == 1]

    def rarest(self, n: int = 10) -> list[Template]:
        return sorted(self.templates, key=lambda t: t.count)[:n]


def extract(lines: list[str], threshold: float = 0.6) -> Extraction:
    """Group lines into templates at the given similarity threshold.

    Lines are bucketed by token count first, as Drain does, because two lines
    of different length are never the same event and comparing them is wasted
    work.
    """
    buckets: dict[int, list[Template]] = {}
    #: token tuple -> the FIRST template in its bucket whose tokens are exactly that.
    #:
    #: A line identical to a template's tokens scores 1.0, which no other candidate can
    #: beat, so the scan can be skipped entirely - and the scan is the whole cost. Each
    #: line is compared against every template in its bucket, so the work is quadratic
    #: in the number of templates: 25,000 lines of a supercomputer log produce 1,858
    #: templates at a threshold of 0.8 and take 60 seconds, and at 0.9 the same input
    #: did not finish in five minutes. Over the nine-system corpus most lines ARE
    #: repeats of a template already seen, which is what makes this worth having.
    #:
    #: "First" matters: `score > best_score` is strict, so where two templates have
    #: become identical the earlier one wins the scan, and this has to agree.
    exact: dict[tuple[str, ...], Template] = {}

    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        tokens = tokenise(raw)
        bucket = buckets.setdefault(len(tokens), [])

        hit = exact.get(tuple(tokens))
        if hit is not None:
            # Merging identical tokens cannot change them, so the template's key stays
            # valid and `exact` needs no repair here.
            hit.count += 1
            hit.members[" ".join(tokens)] += 1
            continue

        best: Template | None = None
        best_score = 0.0
        for candidate in bucket:
            score = _similarity(candidate.tokens, tokens)
            if score > best_score:
                best, best_score = candidate, score
                if score == 1.0:
                    break  # nothing can beat it, and the scan is the cost

        if best is not None and best_score >= threshold:
            was = tuple(best.tokens)
            best.tokens = _merge(best.tokens, tokens)
            best.count += 1
            best.members[" ".join(tokens)] += 1
            now = tuple(best.tokens)
            if now != was:
                # The merge generalised it, so its old key describes it no longer.
                #
                # Defensive, and known to be: a line equal to the OLD tokens mismatches
                # the new ones only at the positions the merge wildcarded, which is the
                # same count that merge needed to be within the threshold - so it would
                # score at or above the threshold and land on this same template anyway.
                # No input in `test_exact_match_index.py`, and none in the nine-system
                # corpus at any of the seven thresholds, distinguishes keeping this from
                # dropping it. It is kept because it costs one comparison and keeps the
                # index's meaning exactly what its comment says, rather than something
                # that happens to be equivalent.
                if exact.get(was) is best:
                    del exact[was]
                exact.setdefault(now, best)
        else:
            template = Template(tokens=tokens, count=1, first_line=number)
            template.members[" ".join(tokens)] += 1
            bucket.append(template)
            exact.setdefault(tuple(tokens), template)

    templates = [t for bucket in buckets.values() for t in bucket]
    templates.sort(key=lambda t: -t.count)
    return Extraction(
        templates=templates,
        lines=sum(t.count for t in templates),
        threshold=threshold,
        lines_read=len(lines),
    )


def sweep(
    lines: list[str], thresholds: tuple[float, ...] = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
) -> list[Extraction]:
    """The same log at several thresholds, to show what compression costs."""
    return [extract(lines, t) for t in thresholds]
