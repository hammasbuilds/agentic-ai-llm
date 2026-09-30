<h1 align="center">compliance-auditor</h1>
<p align="center"><i>Stated policy checked against collected evidence. No inferred compliance.</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-34-success" alt="tests">
  <img src="https://img.shields.io/badge/repos%20audited-37-orange" alt="repos">
</p>

---

## Results

**The most confidently stated convention in the portfolio is the least followed.**

`PROJECTS.md` lists as a house rule, applying to every repository:

> *Every README has a "what it does NOT do" section — overclaiming wastes a reader's time.*

Audited across 37 repositories, it holds in **9 of 33** — **27%**.

```
  37 repositories  -  248/340 controls passed (73%)

  pass 248   fail 92   inconclusive 12   n/a 18
  Inconclusive and n/a are excluded from the rate, never counted as passes.

  BY CONTROL
      9/33   27%  readme-limits     Every README has a 'what it does NOT do' section.
     17/31   55%  deps-used         Every declared dependency is actually imported.
     19/33   58%  readme-io         Every README states what goes in and what comes out.
     25/37   68%  licence           Every repository has a LICENSE.
     26/37   70%  backed-up         Every repository has a git remote.
     27/33   82%  readme-problems   Every README has 'problems hit while building this'.
     27/31   87%  imports-declared  Every third-party import is declared.
     33/37   89%  readme-exists     Every repository has a README of substance.
     33/36   92%  tests-exist       Every repository with source has tests.
     32/32  100%  no-junk           No caches, venvs, logs or secrets are tracked.
```

A written convention is not evidence that the convention was followed. That is the whole
observation, and it is unremarkable until someone measures it.

## The rule that makes the number mean something

**A control may return PASS only when a collector actually observed something.**

Where nothing could be observed - no README to search, no `pyproject.toml` to read - the
result is `inconclusive` or `n/a`, and those are **excluded from the rate rather than
counted as passes**. Twelve inconclusive and eighteen not-applicable results are held out
of the 73% above.

Counting unmeasured controls as passes is how an audit reports a comfortable number
having checked a fraction of what it claimed. The UI draws pass, fail and *unmeasured* as
three visually distinct states for the same reason.

## Input / Output

**In:** a folder of repositories, or one repository.

**Out:**

```
$ compliance-auditor audit D:\github
$ compliance-auditor audit D:\github\rag-forge --one
$ compliance-auditor audit D:\github --json audit.json --strict   # exit 1 on any failure
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
uv run pytest -q                              # 34 tests
uv run compliance-auditor audit D:\github
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
