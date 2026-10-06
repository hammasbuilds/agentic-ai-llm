<h1 align="center">agent infrastructure</h1>
<p align="center"><i>Eleven tools. Zero runtime dependencies, zero LLM calls, zero network.</i></p>

<p align="center"><a href="../README.md">&larr; back to the repository</a></p>

---

Each of these was built around something that turned out to be wrong — a check that passed
for the wrong reason, a number that meant nothing, a rewrite that changed behaviour while
claiming not to. The tool is what remains after the mistake was understood.

They share a constraint: **no model is consulted, and nothing is downloaded.** Where a
judgement cannot be made from the code, the data or the standard library, these refuse to
make it rather than asking something to guess.

| # | Tool | What it does |
|---|---|---|
| 01 | [**repo-cartographer**](01_repo-cartographer) | Map an unfamiliar Python codebase from its AST — no embeddings, no model |
| 02 | [**test-smith**](02_test-smith) | Mutation testing from the standard library: does the suite catch the change, or merely run it? |
| 03 | [**review-bot**](03_review-bot) | Propose findings, then try to disprove each one. Report only what survives |
| 04 | [**migration-pilot**](04_migration-pilot) | Modernise Python where the rewrite is provably equivalent, and refuse where it would change behaviour |
| 05 | [**release-captain**](05_release-captain) | Release readiness scored from diff statistics, not from opinion |
| 06 | [**db-surgeon**](06_db-surgeon) | Prove a migration's rollback on a throwaway copy before trusting it |
| 07 | [**compliance-auditor**](07_compliance-auditor) | Stated policy checked against collected evidence. No inferred compliance |
| 08 | [**csv-analyst**](08_csv-analyst) | Profile a CSV, compute only what validates, and never narrate a number that was not computed |
| 09 | [**log-detective**](09_log-detective) | Extract log templates, and report what the extraction destroyed |
| 10 | [**contract-reader**](10_contract-reader) | Read a licence, and cite the character span behind every claim |
| 11 | [**study-tutor**](11_study-tutor) | Spaced repetition where the scheduler is arithmetic and the model only writes questions |

**527 tests across the eleven**, every one of them runnable without a network, a model or a
GPU. The per-package counts are in the table that `scripts/test_all.py` prints.

On a fresh clone **477 run and 25 skip**. Four suites read data that is not in the
repository: `repo-cartographer` has thirteen tests, `compliance-auditor` two and
`release-captain` one that need a folder of real git checkouts (`REPOS_ROOT`), and
`csv-analyst` nine that need the Online Retail II corpus (`CSV_CORPUS`). All four
default to a path beside this checkout, so all 527 run on the machine they were written
on.

That default is why `scripts/test_all.py --write-counts` runs every suite with those
inputs pointed at an empty directory, and why the per-package lines say "passed,
skipped" rather than a single total. The figure was **444 run / 14 skip** here until
`CSV_CORPUS` was added to the list the sweep withholds: csv-analyst had been reading a
sibling checkout throughout a sweep whose output is labelled "what every suite really
did on a fresh clone", and its nine corpus tests are the ones behind its headline. A
published figure a reader cannot reproduce is not the figure to publish.

## Running them

Each is a separate package with its own `pyproject.toml`, so they do not share a virtual
environment and one cannot break another:

```bash
cd 01_repo-cartographer
python -m pytest -q
```

To run all eleven suites, each in its own process, from the repository root:

```bash
python scripts/test_all.py projects
```

Running plain `pytest` at the repository root does **not** run them, by design — the root
config tells pytest not to descend here, because these packages each put their own `src` on
the path and collecting them together produces dozens of import errors that look like a
broken repository rather than a layout working as intended.

Separate processes on purpose. These are eleven packages that happen to live in one
repository; collecting them into a single pytest session lets one package's `conftest.py`,
`sys.path` entry or module name decide what another package imports, and a suite that only
passes because of what a sibling did first is not evidence about anything.
