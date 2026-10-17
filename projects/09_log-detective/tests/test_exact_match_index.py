"""The exact-match index is an optimisation, so it has to change no result.

Clustering compares every line against every template in its token-count bucket, so the
cost is quadratic in the number of templates. A line whose tokens are already exactly
some template's score 1.0, which nothing can beat, so the scan can be skipped - and the
scan is the whole cost.

The reason to test it rather than measure it is that a cache keyed on a mutable value is
the kind of optimisation that is right until a merge changes the key. So each test runs
the indexed loop and the loop without it over the same lines and requires the same
templates, counts, first lines and members.

What these do NOT show is that the staleness repair in `extract` is load-bearing. It is
not, and it says so: a line equal to a template's pre-merge tokens scores at or above the
threshold against the post-merge ones and lands on that same template either way. These
are an equivalence check over the shapes real logs have, which is what caught nothing and
is the point - the nine-system corpus agrees at all seven thresholds too.
"""

from __future__ import annotations

from detective.templates import Template, _merge, _similarity, extract, tokenise


def reference(lines: list[str], threshold: float = 0.6):
    """The loop without the index. The definition the fast path has to agree with."""
    buckets: dict[int, list[Template]] = {}
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        tokens = tokenise(raw)
        bucket = buckets.setdefault(len(tokens), [])
        best: Template | None = None
        best_score = 0.0
        for candidate in bucket:
            score = _similarity(candidate.tokens, tokens)
            if score > best_score:
                best, best_score = candidate, score
        if best is not None and best_score >= threshold:
            best.tokens = _merge(best.tokens, tokens)
            best.count += 1
            best.members[" ".join(tokens)] += 1
        else:
            template = Template(tokens=tokens, count=1, first_line=number)
            template.members[" ".join(tokens)] += 1
            bucket.append(template)
    return [t for bucket in buckets.values() for t in bucket]


def fingerprint(templates) -> list:
    return sorted(
        (tuple(t.tokens), t.count, t.first_line, tuple(sorted(t.members.items())))
        for t in templates
    )


def agree(lines: list[str], threshold: float) -> None:
    assert fingerprint(extract(lines, threshold).templates) == fingerprint(
        reference(list(lines), threshold)
    ), (threshold, lines[:4])


REPEATS = [
    f"Jun 9 06:06:{i % 60:02d} combo sshd: session opened for user root" for i in range(60)
]
DISTINCT = [f"[error] client 10.0.0.{i} jk2_init failed worker {i}" for i in range(60)]
GENERALISING = [
    "worker 1 started on port 8080 with 4 threads",
    "worker 2 started on port 8081 with 4 threads",
    "worker 3 started on port 8080 with 8 threads",
    "worker 1 started on port 8080 with 4 threads",
]
MIXED = REPEATS + DISTINCT + GENERALISING + ["", "   "] + REPEATS[:10]


def test_repeated_lines_agree():
    """The case the index exists for: every line after the first is an exact hit."""
    for threshold in (0.9, 0.7, 0.5, 0.3):
        agree(REPEATS, threshold)


def test_distinct_lines_agree():
    """The case it cannot help with, where it must also not hurt."""
    for threshold in (0.9, 0.7, 0.5, 0.3):
        agree(DISTINCT, threshold)


def test_a_template_that_generalises_after_a_merge_agrees():
    """A merge rewrites the template's tokens, so the key it was stored under no longer
    describes it. Left stale, a later line matches a template that has moved on."""
    for threshold in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
        agree(GENERALISING, threshold)


def test_a_line_repeated_after_its_template_generalised_agrees():
    """The exact line comes back once its own template has been widened by another."""
    lines = GENERALISING + [GENERALISING[0], GENERALISING[0]]
    for threshold in (0.9, 0.7, 0.5):
        agree(lines, threshold)


def test_everything_together_agrees():
    for threshold in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
        agree(MIXED, threshold)


def test_blank_lines_are_still_not_scored():
    result = extract(["a b c", "", "   ", "a b c"], 0.6)
    assert result.lines == 2
    assert result.lines_read == 4
    assert sum(t.count for t in result.templates) == 2
