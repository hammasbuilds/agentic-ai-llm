<h1 align="center">compliance-auditor</h1>
<p align="center"><i>Stated policy checked against collected evidence. No inferred compliance.</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-44-success" alt="tests">
  <img src="https://img.shields.io/badge/repos%20audited-37-orange" alt="repos">
</p>

---

## Results

**The most confidently stated convention in the portfolio is the least followed.**

`PROJECTS.md` lists as a house rule, applying to every repository:

> *Every README has a "what it does NOT do" section — overclaiming wastes a reader's time.*

Audited across every checkout in one folder — 78 of them, not a chosen subset — it
holds in **14 of 76** — **18%**.

Measured 2026-10-06 over a folder of live checkouts, so it is a snapshot: committing to any of them moves it. The shape of the finding has survived every re-run; the exact counts have not.

```
  78 repositories  -  464/740 controls passed (63%)

  pass 464   fail 276   inconclusive 6   n/a 34
  Inconclusive and n/a are excluded from the rate, never counted as passes.

  BY CONTROL
     13/76   17%  readme-problems
               Every README has 'problems hit while building this'.
     14/76   18%  readme-limits
               Every README has a 'what it does NOT do' section.
     21/76   28%  readme-io
               Every README states what goes in and what comes out.
     23/64   36%  deps-used
               Every declared dependency is actually imported.
     44/64   69%  imports-declared
               Every third-party import is declared.
     66/78   85%  licence
               Every repository has a LICENSE.
     65/76   86%  no-junk
               No caches, venvs, logs or secrets are tracked.
     68/74   92%  tests-exist
               Every repository with source has tests.
     74/78   95%  backed-up
               Every repository has a git remote.
     76/78   97%  readme-exists
               Every repository has a README of substance.

  LOWEST-SCORING REPOSITORIES
      0%  kaggle-notebooks-new         readme-exists, tests-exist, licence, backed-up
     20%  vision-language-lab          readme-exists, tests-exist, licence, backed-up
     29%  private repos                readme-limits, readme-problems, readme-io, licence
     38%  3d-computer-vision           readme-limits, readme-problems, readme-io, licence
     38%  deep-computer-vision         readme-limits, readme-problems, readme-io, tests-exist
     38%  generative-vision-lab        readme-limits, readme-problems, readme-io, tests-exist
     38%  super-resolution             readme-limits, readme-problems, readme-io, tests-exist
     38%  visual-analytics             readme-limits, readme-problems, readme-io, tests-exist
```

A written convention is not evidence that the convention was followed. That is the whole
observation, and it is unremarkable until someone measures it.

## The rule that makes the number mean something

**A control may return PASS only when a collector actually observed something.**

Where nothing could be observed - no README to search, no `pyproject.toml` to read - the
result is `inconclusive` or `n/a`, and those are **excluded from the rate rather than
counted as passes**. Six inconclusive and thirty-four not-applicable results are held out of the 63%
above.

Counting unmeasured controls as passes is how an audit reports a comfortable number
having checked a fraction of what it claimed. The UI draws pass, fail and *unmeasured* as
three visually distinct states for the same reason.

## Input / Output

**In:** a folder of repositories, or one repository.

**Out:**

```
$ compliance-auditor audit ~/code
$ compliance-auditor audit ~/code/rag-forge --one
$ compliance-auditor audit ~/code --json audit.json --strict   # exit 1 on any failure
$ compliance-auditor policy      # print what each control asserts, to argue with
$ python ui/serve.py             # Lit UI on :8100
```

Each result names the policy, what was found, and the file it was found in:

```
  [FAIL] readme-limits
          policy: Every README has a 'what it does NOT do' section.
          found : no heading matching 'what it does NOT do' among 14 headings
          in    : README.md
```

## Results

**Four repositories import packages they never declare** — code that works on this
machine and fails on anyone else's: `machine-learning` (plotly, streamlit), `mcp-lab`
(langchain_mcp_adapters), `rag-forge` (streamlit), `sql-analyst-agent` (pandas,
streamlit). Every one is Streamlit or a plotting library left behind by a deleted
dashboard.

**Fourteen repositories declare dependencies nothing imports** — `uvicorn` in three,
`ruff` declared as a runtime dependency in two, and `accelerate`, `bitsandbytes` and
`datasets` in `qlora-finetune-suite`.

**Ten of 37 have no remote.** Four are not git repositories at all: `computer-vision`,
`multimodal-emotion`, `infra` and `swe` hold real work on one disk with no copy anywhere.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. `tomllib` and `ast` are standard library,
`git` is shelled out to, and the UI is Lit loaded from a CDN as an ES module - no npm, no
build step, the `.js` file in `ui/` is the source that runs.

## Scope

- **It checks conventions, not correctness.** A README with a "what it does NOT do"
  heading passes whether or not the section says anything true.
- **The controls are opinions.** They encode one portfolio's house rules. `policy` prints
  all ten so they can be disagreed with; changing them is editing one tuple.
- **Heading matching is textual.** A section titled "Scope" that describes limitations
  will be marked as failing, and that is a false negative this tool will not catch.
- **Python only** for the dependency controls. A JavaScript project scores `n/a`.
- **No history.** It audits the working tree as it is now, not whether compliance is
  improving.
- **It does not fix anything**, and it deliberately does not offer to.

## Run it

```bash
uv run pytest -q                              # 44 tests
uv run compliance-auditor audit ~/code
uv run compliance-auditor policy
uv run python ui/serve.py                     # :8100
```

## Layout

```
src/auditor/
    evidence.py   collectors: README, pyproject, AST imports, git facts
    controls.py   ten controls, each a policy plus a check
    report.py     aggregation and rendering; the rate excludes unmeasured
    cli.py        argparse
ui/               Lit web component from a CDN, served by http.server
tests/
    test_evidence.py  16 tests
    test_controls.py  18 tests (parametrised)
```
