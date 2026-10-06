<h1 align="center">review-bot</h1>
<p align="center"><i>Propose findings, then try to disprove each one. Report only what survives.</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-43-success" alt="tests">
  <img src="https://img.shields.io/badge/files%20measured-2%2C110-orange" alt="files">
</p>

---

## Results

**Across 2,110 source files, 33% of the findings this reviewer would have posted were
wrong — and for one rule, every single one of them was.**

```
$ review-bot scan <folder of checkouts>

  BY RULE  (proposed / confirmed)
    assert-in-source           208 / 207   0% retracted
    open-without-with          188 / 58    69% retracted
    swallowed-exception          9 / 8     11% retracted
    bare-except                  5 / 0     100% retracted
    mutate-while-iterating       2 / 2     0% retracted
    mutable-default              2 / 2     0% retracted

==============================================================================
  SOURCE FILES ONLY: files=2,110  proposed=414  confirmed=277  retracted=137 (33%)
  2 file(s) are not parseable Python and are not in that count: ...
  (926 test files skipped; pass --include-tests to review them)
```

That `SOURCE FILES ONLY` line used to be quoted here in a format the command never
printed, over a population the command never counted: `scan` reported per-rule proposals
and confirmations and no file total at all. It prints the denominator now, with the test
files it skipped and any file it could not read, because a retraction rate with no file
count under it is not a readable number. Re-run over the folder as it stands, 1,325 files
became 2,110 and 24% retracted became 33%.

The two unparseable files are excluded rather than counted. `propose` returned an empty
list on `SyntaxError`, so a file no rule could run over printed as a reviewed file with
nothing found - identical output to a clean one, and work that did not happen sitting in
the denominator of every per-file figure. Measured 2026-10-06 — a folder of live
checkouts, so the file count moves with it. What has not moved across re-runs is
which rule is retracted and which is not.

**`bare-except` is retracted every time.** Three of the five re-raise after cleanup, so
nothing is swallowed; the other two the author marked `noqa`. It is a textbook lint
finding, confidently reportable from the AST alone, and not once worth posting here.

`swallowed-exception` was the second rule at 100% — on three proposals and zero
confirmations. Over the larger corpus it is 9 proposed and 8 confirmed, with the single
retraction a `noqa`. **A rule measured on three instances was never measured**, and that
is more useful than the 100% was. This README led with "for two rules, 100% of them were
wrong" on the strength of it.

`open-without-with` is the volume case: 188 proposals, 58 real, 130 retracted. 126 of
those are calls already inside a `with` statement, one is a handle consumed immediately
and not retained, and three are marked `noqa`. One proposer accounts for 95% of
everything this reviewer gets wrong.

**Precision is the entire product.** A reviewer that posts a plausible-looking wrong
comment gets muted on the second day, and after that its correct findings are worth
comment gets muted on the second day, and after that its correct findings are worth
nothing either.

## How it works

Two stages, deliberately adversarial:

1. **Proposers are over-eager.** They guess from the AST. A proposer that only fired when
   certain would find almost nothing.
2. **Verifiers try to defeat each proposal.** A finding is reported only if no defeater
   applies. Anything knocked down is recorded *with the reason*, and the retraction rate
   is printed on every run.

Verifiers read the **whole file**, while findings are restricted to lines the diff
**added**. That asymmetry is the design: most false positives are false because of
something the diff did not show — a `raise` three lines below, a `sqlalchemy` import at
the top of the file, a `# noqa` the author already wrote.

## Input / Output

**In:** a git repository and a ref, or a folder of Python files.

**Out:** the findings that survived verification, the ones that did not and why, and the
retraction rate per rule.

```
$ review-bot scan requests/ --show-retracted

  3 finding(s) to report  -  4 of 7 proposals retracted (57%)

  requests\packages\urllib3\packages\ordered_dict.py
    line   197  [bug] mutable-default
              dict used as a default argument in __repr__(); it is created once
              and shared between calls

  RETRACTED  (proposed, then defeated)
    requests\adapters.py:460 bare-except
              defeated: the handler re-raises, so nothing is swallowed
    setup.py:50 open-without-with
              defeated: the call is already inside a `with` statement
```

```
$ review-bot diff <repo> --ref HEAD~1     # review only what a change added
$ review-bot diff <repo> --strict         # exit 1 if anything is reported
$ review-bot rules                        # which proposers have defeaters
$ python ui/server.py                     # API for the Remix UI on :8110
```

## The defeaters

| Rule | What defeats it |
|---|---|
| `mutable-default` | the default is never mutated inside the function, so sharing it is unobservable |
| `bare-except` | the handler re-raises |
| `swallowed-exception` | a nearby comment explains the intent |
| `eq-none`, `eq-bool` | the file imports SQLAlchemy, Django, pandas or similar, where `== None` builds a query expression and `is None` would be wrong |
| `open-without-with` | already inside a `with`, or the handle is consumed immediately |
| `assert-in-source` | the file is a test |
| *any* | the author wrote `noqa`, `nosec`, `intentional`, `deliberate`, `on purpose` or `by design` nearby |

Respecting acknowledgement markers is not politeness. Re-raising something the author
already marked, every run, is precisely how a bot gets turned off.

## A measurement trap worth naming

The first run of this reported a spectacular retraction rate, and it was an artefact of
one badly scoped proposer dominating the denominator. Re-measured over the folder, with
`--include-tests` to reproduce the mistake:

```
  BY RULE  (proposed / confirmed)
    assert-in-source         23843 / 207   99% retracted
    open-without-with          251 / 79    69% retracted
    swallowed-exception         27 / 26    4% retracted
    bare-except                  5 / 0     100% retracted
    mutate-while-iterating       3 / 3     0% retracted
    mutable-default              2 / 2     0% retracted

  ALL FILES: files=3,028  proposed=24131  confirmed=317  retracted=23814 (99%)
```

**99% retracted**, and 23,635 of the 23,814 defeats are one proposer being told "the file
is a test". Subtract the test files and `assert-in-source` proposes 208 times and is
retracted once; everything else in the table barely moves.

A review bot does not lint asserts in a test suite, so test files are excluded by default
and the honest number is 33%. The 99% is not reported anywhere except here, as the mistake
it was — and it is worth keeping runnable, because the shape of it is the most common way
a precision number gets published too high.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. `ast` proposes, `subprocess` reads
`git diff`, a small parser handles unified-diff hunks, and the API is `http.server`. Only
the Remix front end needs npm.

No model is involved. A model would write better explanations and would also confirm
findings it had not checked, which is the failure this project is built to avoid.

## Scope

- **Seven rules.** This is not a linter and does not want to be. The contribution is the
  verification stage, which any rule set could be dropped into.
- **It cannot know intent.** Every defeater is a heuristic, and `mutable-default` in
  particular guesses from whether the parameter is mutated *in that function* — a helper
  that mutates it elsewhere would be missed.
- **No cross-file analysis.** A defeater living in another module is invisible.
- **Python only.**
- **It does not post comments anywhere.** It prints and exits; wiring it to a forge is
  deliberately left out.
- **A 33% retraction rate is not 100% precision.** It means 33% of what would have been
  posted was caught first. The remainder has not been independently validated, and on a
  different codebase every number here would change.

## Run it

```bash
uv run pytest -q                              # 46 tests
uv run review-bot scan <path> --show-retracted
uv run review-bot diff <repo> --ref HEAD~1
uv run python ui/server.py                    # then: cd ui && npm install && npm run dev
```

## Layout

```
src/reviewbot/
    checks.py   over-eager proposers, seven rules
    verify.py   defeaters, one per rule, plus acknowledgement markers
    review.py   diff parsing, scoping, aggregation, rendering
    cli.py      argparse
ui/             Remix front end, http.server API
tests/test_review.py   36 tests, mostly about what it refuses to report
```
