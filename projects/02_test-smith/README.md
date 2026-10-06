<h1 align="center">test-smith</h1>
<p align="center"><i>Mutation testing from the standard library - does the suite catch the change, or merely run the line?</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-35-success" alt="tests">
  <img src="https://img.shields.io/badge/repos%20measured-8-orange" alt="repos">
</p>

---

## Results

**Across 8 repositories and 320 mutants, 62 deliberate bugs survived on lines the test
suite had just executed.** Those lines are green in any coverage report. The test ran
them, the code was wrong, and nothing failed.

And the failures are not spread evenly. Split by what was mutated:

| Mutation | Caught | Rate | |
|---|---|---|---|
| `not x` removed | 18 / 21 | **86%** | control flow |
| `return expr` → `return None` | 54 / 73 | **74%** | control flow |
| `<` → `<=`, `==` → `!=` | 25 / 36 | **69%** | control flow |
| `+` → `-`, `*` → `/` | 14 / 23 | **61%** | arithmetic |
| `and` → `or` | 6 / 17 | **35%** | logic |
| a literal changed | 45 / 143 | **31%** | values |

**Test suites check control flow. They barely check values.** A mutation to a constant -
a threshold, a default, a fallback - survives more than two times in three, while removing
a `not` is caught six times in seven. Every suite measured shows the same shape.

This is not a claim about these repositories being badly tested. They are ordinarily
tested, which is the point: the gap is in what a normal testing habit produces.

## Input / Output

**In:** a path to a Python repository whose test suite currently passes.

**Out:**

```
$ testsmith run ~/code/credit-risk-engine --limit 40

  OUTCOMES
    killed      23
    survived    17
    timeout      0   (counted as caught)
    error        0   (excluded - broke the import, proves nothing)

  SCORE
    overall            57%  over 40 scored mutants
    on executed lines  77%  over 30 mutants

  THE FINDING - survivors on lines the suite executed
  A coverage report marks these lines green. The test ran them, the code
  was wrong, and nothing failed.

    src/creditrisk/fairness.py:49
        constant: 0.0  ->  1.0
    src/creditrisk/fairness.py:50
        constant: 0.0  ->  1.0
    src/creditrisk/scorecard.py:46
        constant: 600  ->  0
    src/creditrisk/binning.py:62
        binop: /  ->  *

  Also 10 survivor(s) on lines no test ever reached - a coverage
  gap rather than a test-quality one.
```

Also:

```
$ testsmith preview <repo> -v          # list mutants without running anything
$ testsmith run <repo> --only fairness # restrict to matching paths
$ testsmith run <repo> --json out.json # machine-readable report
$ uv run --extra ui python ui/app.py   # NiceGUI front end on :8081
```

## Measured

Forty mutants per repository, sampled round-robin across files so the cap does not simply
measure the alphabetically-first module.

| Repository | Mutants | Killed | Survived | Score | On executed lines | Survivors on executed lines |
|---|---|---|---|---|---|---|
| urdu-nlp-toolkit | 40 | 27 | 13 | 68% | 79% | 7 |
| credit-risk-engine | 40 | 23 | 17 | 57% | 77% | 7 |
| deep-research-agent | 40 | 17 | 23 | 42% | 62% | 9 |
| demand-forecast-platform | 40 | 21 | 19 | 52% | 81% | 5 |
| insurance-mlops | 40 | 18 | 22 | 45% | 60% | 12 |
| pak-law-assistant | 40 | 19 | 15 | 56% | 83% | 4 |
| incident-copilot | 40 | 16 | 24 | 40% | 67% | 8 |
| doc-intelligence-api | 40 | 21 | 18 | 54% | 68% | 10 |
| **median** | | | | **53%** | **72%** | |

The two score columns differ by about twenty points everywhere, and the difference is the
whole argument for measuring both. The overall score conflates *"no test reaches this
code"* with *"a test reaches it and does not check it"*. Only the second is a statement
about test quality; the first is a coverage statement you already had.

## Two real gaps this found

**`urdu-nlp-toolkit` - half the digit normalisation is unguarded.**
`ARABIC_INDIC_DIGITS` at `normalize.py:42` can be replaced with an empty dict and all 40
tests still pass. The one digit test uses `normalize("۱۲۳")` - Urdu digits at U+06F0 -
while Arabic-Indic digits at U+0660 are never exercised, despite the code's own comment
saying *"Urdu uses Extended Arabic-Indic (U+06F0), Arabic uses U+0660. Both occur."* The
implementation is correct; both forms normalise. It is simply not defended, and deleting
that line leaves CI green.

**`credit-risk-engine` - the fairness audit's empty-group fallbacks are never taken.**
`fairness.py:49-50` computes `sum(...) / len(goods) if goods else 0.0`. Mutating `0.0` to
`1.0` survives, because no test passes a protected group with zero goods or zero bads. In
a fairness report, a tiny subgroup is exactly the case that decides whether the report is
trustworthy.

## Two decisions that change the number

**Mutants that break the import are excluded, not counted as kills.** A mutant that stops
the module loading never reached an assertion, so it is no evidence at all about the test
suite. Counting collection errors as kills is the standard way a mutation score gets
quietly inflated - `pak-law-assistant` had 6 of these and `doc-intelligence-api` 1, and
scoring them as wins would have added several points to both for nothing.

The exclusion runs the other way too, and used to. It is applied only to a mutant that
would otherwise be a kill, and it removes that mutant from the numerator *and* the
denominator - so a false positive can only move the score **up**. It was decided by
substring-matching `ImportError` against the whole of pytest's output, which is also
what pytest prints when a test *fails* with that word in its message. A suite that
asserts on a raised `ImportError` had its kills quietly removed; on a repository built
to show it, this tool reported 100% over one scored mutant. It now takes only pytest's
own collection markers, or that word together with pytest's interrupted exit code.

**Timeouts are counted as caught.** A mutant that sends the suite into an infinite loop
did not slip through silently, and the suite did notice. This is the conservative
direction: it makes the tool look *less* impressive, not more.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`.

`mutmut` and `coverage.py` were the obvious dependencies and neither is needed: `ast`
applies the mutations, `subprocess` runs the suite, and `sys.settrace` records which lines
executed. `nicegui` is an optional extra used only by the UI - the measurement never
imports it.

## Scope

- **Never writes to the repository under test.** The tree is copied to a scratch workspace
  and the original is never opened for writing. A test asserts the source file's mtime is
  unchanged after a full run. If this tool ever corrupts the code it is grading, that test
  was deleted.
- **Refuses a red suite.** A mutation score against failing tests is meaningless, so the
  run aborts with the pytest output rather than producing a number.
- **Does not detect equivalent mutants.** Some survivors are changes that genuinely cannot
  alter behaviour. This is undecidable in general and is not attempted; it means the true
  score is somewhat higher than reported.
- **Python only**, and `pytest` only.
- **Slow by nature.** One full suite run per mutant. The default cap is there because a
  complete run on a large repository is an overnight job, not a pre-commit hook.
- **Does not write tests for you.** It tells you precisely which assertion is missing and
  where. Writing it is still your job.

## Run it

```bash
uv run pytest -q                                   # 39 tests
uv run testsmith run <repo> --limit 40
uv run python scripts/sweep.py 40                  # reproduces the table above
uv run --extra ui python ui/app.py                 # UI on :8081
```

## Layout

```
src/testsmith/
    mutate.py     six operators over the AST, one change per mutant
    coverage.py   sys.settrace line coverage, no dependency
    runner.py     scratch workspace, suite execution, the covered/uncovered split
    report.py     text and JSON
    cli.py        argparse
ui/app.py         NiceGUI front end (optional extra)
scripts/sweep.py  produces every number in this README
tests/
    test_mutate.py   26 tests (parametrised)
    test_runner.py   13 tests
```
