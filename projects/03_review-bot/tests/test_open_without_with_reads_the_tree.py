"""The defeater behind 130 of the 137 retractions read one line of raw text.

    if stripped.startswith("with ") or " with " in stripped:
        return "the call is already inside a `with` statement"

Two wrong answers, both reproduced by an independent reviewer on one ten-line file:

    handle = open(path)   # we will deal with it later
        -> RETRACTED "the call is already inside a `with` statement"   (it leaks)

    with contextlib.closing(
            open(path)) as fh:
        -> REPORTED "open() result may not be closed"                  (it is closed)

`review-bot scan --show-retracted` printed "1 finding(s) to report - 1 of 2 proposals
retracted", exactly inverted. The retraction reason is the part that matters: this module
exists so that a dismissal is a disproof, and "already inside a `with` statement" was a
false statement about the code, produced by a comment.

A `with` spans lines and a comment is not code, so neither question can be answered by
one line of text. Both are asked of the tree the context already parses.
"""

from __future__ import annotations

import textwrap

import pytest

from reviewbot.checks import propose
from reviewbot.verify import FileContext, verify

RULE = "open-without-with"

REPORTED = "reported"
RETRACTED = "retracted"

CASES: dict[str, tuple[str, str]] = {
    # -- the two the reviewer found, which were the wrong way round -------------
    "a leak whose comment contains the word with": (
        """
        def leaks(path):
            handle = open(path)   # we will deal with it later
            return handle
        """,
        REPORTED,
    ),
    "closed by contextlib.closing, with on the previous line": (
        """
        import contextlib


        def closed(path):
            with contextlib.closing(
                    open(path)) as fh:
                return fh.read()
        """,
        RETRACTED,
    ),
    # -- the cases that already worked, which have to go on working -------------
    "a plain with": (
        """
        def ok(path):
            with open(path) as fh:
                return fh.read()
        """,
        RETRACTED,
    ),
    "consumed immediately": (
        """
        def quick(path):
            return open(path).read()
        """,
        RETRACTED,
    ),
    "written immediately": (
        """
        def dump(path, text):
            return open(path, "w").write(text)
        """,
        RETRACTED,
    ),
    "a leak with no comment at all": (
        """
        def leaks(path):
            handle = open(path)
            return handle
        """,
        REPORTED,
    ),
    "stored on self and never closed": (
        """
        class C:
            def __init__(self, path):
                self.fh = open(path)
        """,
        REPORTED,
    ),
    # A handle entered into an ExitStack IS closed, and is not inside a `withitem` -
    # the `with` holds the stack, not the file - so the tree walk alone reported it.
    # `enter_context` takes ownership, which is a fact about the method and is named.
    "entered into an ExitStack": (
        """
        import contextlib


        def staged(path):
            with contextlib.ExitStack() as stack:
                return stack.enter_context(open(path)).read()
        """,
        RETRACTED,
    ),
    "an async with": (
        """
        async def ok(path):
            async with open(path) as fh:
                return fh
        """,
        RETRACTED,
    ),
}


def _verdicts(source: str):
    text = textwrap.dedent(source).lstrip("\n")
    context = FileContext.build("m.py", text)
    return [verify(context, p) for p in propose(text) if p.rule == RULE]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_defeater_answers_the_question_it_claims_to(case: str):
    source, expected = CASES[case]
    verdicts = _verdicts(source)
    assert verdicts, f"{case}: nothing was proposed, so this proves nothing"
    for verdict in verdicts:
        if expected == REPORTED:
            assert verdict.confirmed, (case, verdict.reason)
        else:
            assert not verdict.confirmed, (case, "reported a handle that is closed")
            assert any(
                word in verdict.reason for word in ("with", "consumed", "closes it")
            ), verdict.reason


def test_a_comment_cannot_retract_a_finding():
    """The general version. The word `with` in a comment is a fact about English."""
    for comment in (
        "# we will deal with it later",
        "# TODO: replace with a context manager",
        "# compare with the old implementation",
        "# with great power...",
    ):
        source = f"def leaks(path):\n    handle = open(path)  {comment}\n    return handle\n"
        verdicts = _verdicts(source)
        assert verdicts and all(v.confirmed for v in verdicts), (comment, verdicts)


def test_two_calls_on_one_line_are_told_apart():
    """The reason the proposal now carries a column. One is a `with` context and the
    other leaks, and a line-level answer has to be wrong about one of them."""
    source = (
        "import contextlib\n\n\n"
        "def both(a, b):\n"
        "    with contextlib.closing(open(a)) as fh: leaked = open(b)\n"
        "    return fh, leaked\n"
    )
    verdicts = sorted(_verdicts(source), key=lambda v: v.proposal.evidence["col"])
    assert len(verdicts) == 2, verdicts
    assert not verdicts[0].confirmed, verdicts[0].reason
    assert verdicts[1].confirmed, verdicts[1].reason


def test_every_proposal_carries_a_column():
    """Because a verifier that has to guess which node it is looking at will guess."""
    source = "def f(path):\n    return open(path)\n"
    proposals = propose(source)
    assert proposals
    for proposal in proposals:
        assert "col" in proposal.evidence, proposal
        assert isinstance(proposal.evidence["col"], int), proposal


def test_an_unparseable_file_leaves_the_finding_standing():
    """No tree, no answer. A retraction on a guess is the thing this module is against,
    so the direction to err in is leaving the finding up."""
    context = FileContext.build("m.py", "def f(:\n")
    assert context.tree is None
    # Nothing is proposed from an unparseable file, so the invariant is about the
    # defeater rather than about the pipeline: given a proposal and no tree, it stands.
    from reviewbot.checks import Proposal
    from reviewbot.verify import _defeat_open_without_with

    proposal = Proposal(
        rule=RULE,
        line=1,
        end_line=1,
        message="x",
        severity="smell",
        evidence={"col": 0},
    )
    assert _defeat_open_without_with(context, proposal) is None


def test_the_readme_states_the_number_of_rules_there_are():
    """It said "Seven rules" in two places while `RULES` held eight.

    A rule count is the cheapest figure in the project to check and the one a reader
    uses to decide whether the thing is worth running, so it is read from the code.
    """
    from pathlib import Path

    from reviewbot.checks import RULES

    words = {6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8"
    )
    assert len(RULES) in words, f"{len(RULES)} rules; add the word to this test"
    assert f"**{words[len(RULES)]} rules.**" in readme, (
        f"there are {len(RULES)} rules and the README does not say "
        f"{words[len(RULES)]!r}"
    )
    assert f"{words[len(RULES)].lower()} rules" in readme, (
        "the Layout block still names a different number"
    )
    for count, word in words.items():
        if count == len(RULES):
            continue
        assert f"**{word} rules.**" not in readme, f"the README still says {word!r}"
        assert f"proposers, {word.lower()} rules" not in readme, word
