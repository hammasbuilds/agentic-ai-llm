<h1 align="center">release-captain</h1>
<p align="center"><i>Release readiness scored from diff statistics, not from opinion</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-42-success" alt="tests">
  <img src="https://img.shields.io/badge/repos%20measured-28-orange" alt="repos">
</p>

---

## Results

**The single largest commit across 28 repositories changed 47,743 lines in 5 files. The
third largest changed 5,442 lines in 693 files. Ranked by lines, the first is nine times
worse; ranked by breadth, the second is a hundred and thirty times worse. They are
opposite kinds of risk and every single-number metric ranks one of them wrongly.**

The first is a regenerated results file - almost no review risk. The second is a broad
structural change - a great deal. A release gate that thresholds on lines changed blocks
the harmless one and waves the dangerous one through.

So risk here is a small weighted vector - breadth, file count, untested source, volume,
net deletion - and the report always names which factors produced the number.

## But the honest version is narrower than that

The obvious follow-up claim is that single metrics disagree in general, so a composite is
always necessary. **Measured across 28 repositories, that is false.** Ranked top-5
overlap between metrics:

| Pair | Mean excess over chance |
|---|---|
| lines vs files | **+25%** |
| lines vs spread | **+21%** |
| files vs spread | **+32%** |

The metrics *agree*, well above chance. On ordinary commits, any one of them would do.
The composite earns its place only on the tail - generated-data commits and broad
refactors - and the tail is exactly what a release gate exists for. `mcp-lab`, the repo
with the most history and the 47,743-line dump in it, is the one repository where lines
and spread overlap **below** chance (20% observed against 28% expected).

Reporting "a composite is always better" would have been a nicer headline and it is not
what the data says.

## The measurement trap this walked into first

The first version of that table reported **75-80% overlap** and I nearly wrote it up as
strong agreement. It was an artefact. With 8 commits in a repository and a top-5
comparison, **chance alone produces 62% overlap** - you are choosing 5 of 8 items twice.
Most of these repositories have fewer than a dozen commits, so the raw number measured
history length, not metric agreement.

Every figure above is excess over the chance baseline `top / n`. Raw overlap is not
reported anywhere, because it is not readable.

## Input / Output

**In:** a git repository.

**Out:**

```
$ captain gate ~/code/rag-forge --since 8

==============================================================================
  rag-forge  -  NO-GO
==============================================================================

  8 commit(s) assessed; 4 of 4 checks measured something

  CHECKS
    [STOP] source changes without tests
           2 of 2 source-changing commits changed no test file
    [ok  ] riskiest commit
           38.7 - ab5c97b9 Drop the build diary
    [ok  ] areas touched
           3 top-level areas: (root), deploy, docs
    [ok  ] commits far above this repo's median
           none

  RISKIEST COMMITS  (composite: spread, files, untested, volume, deletion)
     38.7  ab5c97b9     279L    2f 2dir  Drop the build diary
     38.1  53e4dea5      90L    4f 2dir  Add a runnable demo and Input/Output section
     29.0  52cce596      35L    1f 1dir  Tidy demo.py: ruff clean and formatted
     25.5  fb67c6d7      32L    1f 1dir  Reword project notes as implementation and r
==============================================================================
```

Also:

```
$ captain explain <repo> <sha>     # the factor breakdown behind one score
$ captain rank <repo> --by churn   # or files, spread, risk - see them disagree
$ captain sweep ~/code             # gate every checkout - the table below
$ captain compare ~/code           # do single metrics agree, above chance?
$ captain gate <repo> --strict     # exit 1 when blocked, for CI
```

## Applied to the portfolio

`captain sweep <folder> --since 8` over every checkout in one folder, which is where this
table comes from. It used to be quoted over a chosen 28 repositories and no command here
produced it, so it could not go stale visibly - and it had, naming `mcp-lab` as blocked
when `mcp-lab` now reads GO.

| Verdict | Repositories |
|---|---|
| GO | 17 |
| GO WITH WARNINGS | 44 |
| NO-GO | 14 |
| **measured** | **75** |

**13 of the 14 blocked are blocked by the same check: every recent source-changing commit
changed no test file.** The other three blocks are a single commit scoring past 65. Not a
subtle signal, and not one a line-count threshold would have produced.

### A check that measured nothing is not a check that passed

**6 of those 17 clean GO verdicts rest on a check that had nothing to look at.** All six
shipped only documentation or data in the window, so "no source went out untested" is true
only because no source went out - and the gate used to print for them the same `ok` it
prints for a release whose every source file arrived with a test.

They now read `-` rather than `ok`, the header counts how many checks measured something,
and the report says so at the bottom:

```
$ captain gate ~/code/llm-agentic-datasets --since 8

  4 commit(s) assessed; 3 of 4 checks measured something

  CHECKS
    [ -  ] source changes without tests
           no source changes in range, so test coupling was not observed
    [ok  ] riskiest commit
           34.3 - b17c7996 Add CC BY 4.0 licence and trim the index to the published da
    [ok  ] areas touched
           1 top-level area: (root)
    [ok  ] commits far above this repo's median
           none

  1 check(s) had nothing to look at. A verdict that rests on fewer
  checks is not a stronger one.
```

The verdict is still GO. Nothing was observed, and nothing observed is not a failure - but
it is also not evidence, and a reader could not previously tell the two apart.

## Thresholds are relative to the repository

A 500-line commit is unremarkable where the median is 2,100 lines and alarming where it is
20. Every size threshold is a multiple of that repository's own median - the outlier check
fires at 20x it - which is why it fires at 42,000 lines on `classical-computer-vision`,
7,930 on `mcp-lab` and 2,280 on `langchain-lab` rather than at one number chosen in
advance for all three.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`.

`git` is the data source and is already present anywhere this would run. GitPython was
considered and skipped: `git log --numstat` with a custom format is one subprocess call
and a parser, against a dependency that wraps the same command. The web view is served by
`http.server` from the standard library.

## Scope

- **Does not read commit message conventions.** It was built expecting Conventional
  Commits and the repositories it was measured on use prose subjects, so nothing depends
  on the subject line. Diff statistics are the only input.
- **Weights are declared, not learned.** There is no labelled "this release broke
  production" data here, so `WEIGHTS` encodes a stated position rather than a fitted
  model. They are in one dictionary at the top of `risk.py` and are meant to be argued
  with.
- **No CI integration, no issue tracker, no deploy hook.** It reads history and returns a
  verdict with an exit code.
- **Never writes to the repository.** Every git command is a read.
- **Does not know what your code does.** A one-line change to a payment path and a
  one-line change to a log message score identically.

## Run it

```bash
uv run pytest -q                        # 42 tests
uv run captain gate <repo> --since 8
uv run captain compare ~/code
uv run python ui/serve.py               # web view on :8090
```

## Layout

```
src/captain/
    history.py   git log --numstat parsing, file classification, co-change
    risk.py      the weighted factors and the ranking comparison
    gate.py      the checks, the verdict, and the reason for each
    cli.py       argparse
ui/serve.py      http.server + Alpine.js, no dependency
tests/
    test_history.py  20 tests against real git repositories
    test_risk.py     22 tests
```
