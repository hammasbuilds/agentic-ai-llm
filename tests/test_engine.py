"""The execution rule, which decides the score more than the model does.

`apps/_engine` was 1,452 lines with no tests, and it is the tier the README leads with.
Everything the ten apps report — every pass rate, every mutation-survival number, every
self-debug ceiling — is downstream of `extract_code` and `run`. A defect here does not
make an app crash; it moves a published number and says nothing.

One was there. The success marker was the fixed string `__OK__` and the pass condition
was that it appeared anywhere in stdout, so a candidate that printed it scored `pass`
even when its tests raised:

    candidate: print("__OK__")    tests: assert add(2, 3) == 5
    -> NameError, exit 1, scored `pass`

A candidate returning 0 for every input passed the same way. That is a false accept in
the harness that App 02 built to count false accepts. The marker is now a per-run nonce
and has to be the last line of stdout; the first four tests below are that defect.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._engine.execute import Outcome, extract_code, run, run_many  # noqa: E402

ADD_TEST = "assert add(2, 3) == 5"
HONEST = "def add(a, b):\n    return a + b"


# ---- the false-accept channel --------------------------------------------------------


def test_a_candidate_that_prints_the_old_marker_does_not_pass():
    outcome = run('print("__OK__")', ADD_TEST, timeout=10)
    assert not outcome.passed
    assert outcome.status == "error"  # NameError: add is not defined


def test_a_wrong_candidate_cannot_buy_a_pass_by_printing_the_marker():
    code = 'def add(a, b):\n    return 0\nprint("__OK__")'
    outcome = run(code, ADD_TEST, timeout=10)
    assert outcome.status == "fail"


def test_the_marker_differs_between_runs():
    """A nonce cannot be printed by code that has never seen it."""
    first = run(HONEST, ADD_TEST, timeout=10)
    second = run(HONEST, ADD_TEST, timeout=10)
    assert first.passed and second.passed
    # Printing whatever the previous run used must not help.
    leaked = f'def add(a, b):\n    return 0\nprint("__OK__{"0" * 16}__")'
    assert run(leaked, ADD_TEST, timeout=10).status == "fail"


def test_output_after_the_tests_does_not_stand_in_for_them():
    """The marker has to be last, or trailing output can impersonate success."""
    noisy_tests = [ADD_TEST, 'print("done")']
    assert run(HONEST, noisy_tests, timeout=10).passed
    wrong = run("def add(a, b):\n    return 0", noisy_tests, timeout=10)
    assert wrong.status == "fail"


# ---- the four outcomes are four, not two ---------------------------------------------


@pytest.mark.parametrize(
    "code,tests,status",
    [
        (HONEST, ADD_TEST, "pass"),
        # An assertion failing is the honest way to be wrong.
        ("def add(a, b):\n    return 0", ADD_TEST, "fail"),
        # Anything else is an error, and must not be counted as a tested failure: a
        # candidate caught by crashing would have survived behind a guard clause.
        ('def add(a, b):\n    raise ValueError("no")', ADD_TEST, "error"),
        ("def add(a, b)\n    return a + b", ADD_TEST, "error"),  # SyntaxError
        ("", ADD_TEST, "error"),  # nothing extracted
        ("def add(a, b):\n    while True:\n        pass", ADD_TEST, "timeout"),
    ],
)
def test_the_four_outcomes(code, tests, status):
    assert run(code, tests, timeout=3).status == status


def test_setup_runs_after_the_solution():
    """Setup sometimes instantiates what the solution defines.

    Running setup first raises NameError on perfectly good code, which would be
    scored `error` and counted as the model's failure.
    """
    code = "class Counter:\n    def __init__(self):\n        self.n = 0"
    outcome = run(code, "assert c.n == 0", setup="c = Counter()", timeout=10)
    assert outcome.passed


def test_a_passing_run_reports_no_detail_and_a_failing_one_does():
    assert run(HONEST, ADD_TEST, timeout=10).detail == ""
    assert "AssertionError" in run("def add(a, b):\n    return 0", ADD_TEST, timeout=10).detail


def test_tests_may_be_a_string_or_a_list():
    assert run(HONEST, ADD_TEST, timeout=10).passed
    assert run(HONEST, [ADD_TEST, "assert add(0, 0) == 0"], timeout=10).passed
    assert run(HONEST, [ADD_TEST, "assert add(0, 0) == 1"], timeout=10).status == "fail"


def test_the_candidate_cannot_see_the_repository():
    """It runs in a temporary directory, so a relative read cannot reach this tree."""
    code = "import os\nresult = sorted(os.listdir('.'))"
    outcome = run(code, "assert result == ['candidate.py'], result", timeout=10)
    assert outcome.passed, outcome.detail


# ---- extraction ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```python\ndef f():\n    return 1\n```", "def f():\n    return 1"),
        ("```\ndef f():\n    return 1\n```", "def f():\n    return 1"),
        # Prose around a block: the block wins.
        ("Here you go:\n```python\nx = 1\n```\nHope that helps!", "x = 1"),
        # No fence at all: the whole response, which is deliberate. A stricter rule
        # scores the same generations lower, and that variance belongs to the harness
        # rather than to the model.
        ("def f():\n    return 1", "def f():\n    return 1"),
        ("", ""),
        # The first block, when there are several.
        ("```python\nfirst = 1\n```\nand\n```python\nsecond = 2\n```", "first = 1"),
    ],
)
def test_extract_code(raw, expected):
    assert extract_code(raw) == expected


def test_extracted_code_runs():
    """Extraction and execution have to agree, or a correct answer scores as broken."""
    raw = "Sure:\n```python\ndef add(a, b):\n    return a + b\n```\nThat should do it."
    assert run(extract_code(raw), ADD_TEST, timeout=10).passed


# ---- batching ------------------------------------------------------------------------


def test_run_many_keeps_each_job_with_its_own_result():
    jobs = [
        (HONEST, ADD_TEST, ""),
        ("def add(a, b):\n    return 0", ADD_TEST, ""),
        ('def add(a, b):\n    raise ValueError("no")', ADD_TEST, ""),
    ]
    outcomes = run_many(jobs, workers=3)
    assert [o.status for o in outcomes] == ["pass", "fail", "error"]


def test_an_outcome_knows_whether_it_passed():
    assert Outcome("pass").passed
    for status in ("fail", "error", "timeout"):
        assert not Outcome(status).passed


# ---- what "unproven" actually means ---------------------------------------------------


def test_a_mutant_no_input_ran_against_is_not_reported_like_one_that_was_tried():
    """Both are unproven. Only one of them is evidence about the mutant.

    The probe skips any candidate argument that will not `eval`, which is right - but
    when every candidate is skipped it used to return the same `Witness(found=False)`
    as a mutant that forty inputs failed to separate. The caller kept only `found`, so
    a survivor nothing ever ran against was counted as "either equivalent or not
    separated", which is a claim nothing supported.
    """
    from apps._engine.differential import find_witness

    reference = "def f(n):\n    return n + 1\n"
    mutant = "def f(n):\n    return n + 2\n"

    separated = find_witness(reference, mutant, "f", ("assert f(1) == 2",))
    assert separated.found
    assert separated.cases_run >= 1

    equivalent = find_witness(
        reference, "def f(n):\n    return 1 + n\n", "f", ("assert f(1) == 2",)
    )
    assert not equivalent.found
    assert equivalent.cases_run >= 1
    assert "no separating input found" in equivalent.reason

    # The argument names something that does not exist, so nothing evaluates.
    untried = find_witness(reference, mutant, "f", ("assert f(undefined_name) == 2",))
    assert not untried.found
    assert untried.cases_run == 0
    assert "none evaluated" in untried.reason
    assert untried.candidates >= 1

    # And the three are distinguishable from the outside, which is the point.
    assert len({(w.found, w.cases_run == 0) for w in (separated, equivalent, untried)}) == 3


def test_a_program_is_not_a_witness_against_itself():
    """`_call(f_ref, args)` then `_call(f_mut, args)` shared one object.

    A function that mutates its argument handed the mutant pre-mutated input, so the
    prober reported a separating input between a program and itself — and between a
    reference and an equivalent mutant. Quantified over the first 150 MBPP problems by
    an independent review: 2 of 66 "provably wrong" survivors were artefacts of this,
    and the `mut` value shown in the witness table was not what the mutant produces.
    """
    from apps._engine.differential import find_witness

    mutating = "def f(xs):\n    xs.append(1)\n    return xs\n"
    assert not find_witness(mutating, mutating, "f", ("assert f([0]) == [0, 1]",)).found

    doubled = "def g(n):\n    return n * 2\n"
    added = "def g(n):\n    return n + n\n"
    assert not find_witness(doubled, added, "g", ("assert g(3) == 6",)).found

    # And a real difference is still found, with the mutant's real output.
    witness = find_witness(
        "def h(n):\n    return n + 1\n",
        "def h(n):\n    return n + 2\n",
        "h",
        ("assert h(1) == 2",),
    )
    assert witness.found
    assert witness.ref == "('ok', '2')" and witness.mut == "('ok', '3')"
