# 20 · driftwatch

> Watches a repository for the moment its documentation stops being true, and opens the pull request that fixes it.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured over every checkout in one folder — 76 of them**, their real READMEs, real
`pyproject.toml` files and real directory contents. Not a chosen subset: the previous
figures were over 35, and over the folder every one of them moves. Measured 2026-10-06; it is a snapshot, and committing to any checkout in that folder moves it.

| | |
|---|---:|
| Candidate claims (README sentences) | **10,929** |
| Claims a machine can adjudicate | **300** (2.74%) |
| Of those, claims with a fact to check against | 225 (75.0%) |
| Claims that were checked and reported **false** | **12** (5.3% of checked) |
| Of those, hand-verified as real drift | **5** |

**Fewer than three sentences in a hundred can be settled by a checker.** Doc-linting tools
are built as though that fraction were most of the file, which is why they produce a wall
of unfalsifiable findings and get switched off in week two. The other 97.3% is prose: it
may be wrong, but no tool is going to be the thing that decides.

Note the third row too. A quarter of the mechanically-shaped claims could not be checked
because no fact answered them — a claim being *checkable in principle* and a checker
*having the fact* are different things, and conflating them inflates the headline.

### The five that are real

| Repository | Drift |
|---|---|
| `classical-computer-vision` | README says **57 projects**, "All 57 built"; there are **63** |
| `classical-computer-vision` | a later paragraph still says **41 projects** |
| `browser-agent` | references `scripts/wide_attribution.py`, which does not exist |
| `worktree-fleet` | "All numbers: `results/summary.json`" — no `results/` directory, and it is not gitignored |
| `worktree-fleet` | references `results/report_table.txt`, same |

### And the seven that are not

This is the part worth reading. **12 reported false, 5 of them real: precision is 42%**, so
the majority of what this checker says is still its own bug. Each survivor is a distinct
class, listed because naming them is more useful than a number that sounds better:

| Not drift | Example | Why the checker is wrong |
|---|---|---|
| A demo's output described in prose | `` `out.txt` `` in "read `out.txt` back" | the file is created when the demo runs |
| A third-party model's file | `` `tokenizer.json` `` in harness-ablation (x2) | it lives in a Hugging Face cache |
| A file on somebody else's website | `` `robots.txt` `` in job-radar | Rozee.pk's, not this repository's |
| A file the reader creates | `` `claude_desktop_config.json` `` | on their machine, not in the repo |
| An example command | `` `./script.sh` `` in "`make`, `./script.sh` and `npm run build`" | a command, not a path |
| A gitignored file said to be so elsewhere | `` `trials.json` `` in trial-match | the sentence carrying "(gitignored)" is a different sentence |

**A checker whose first output is an alarming rate is usually measuring itself**, and this
one was still doing it after the first round of fixes.

### What had to be fixed to get this number

The first extractor treated every sentence as a claim and reported 4,757 findings, nearly
all of them unfalsifiable adjectives. Classification has to come before verification, or
the output is noise with the real defects buried in it.

Re-run over the folder rather than the chosen 35, it reported **31 false claims**, and
most were neither false nor claims. Six classes, each now declined rather than accused:

| False positive | Example | Why it isn't drift |
|---|---|---|
| A path under the repository's own `.gitignore` | "the corpus lives in `data/trials.json`" | it was never meant to be tracked |
| A file the same sentence says is produced | "Run `make eval` to generate `RESULTS.md`" | its absence is the documented state |
| A path named as somebody else's | "not `coverage.py`", "Django `runtests.py`", "the zip contains `__MACOSX/._x.txt`" | a counterexample, another project, a download |
| A count of part of the set | "One project per LangGraph shape", "Two projects changed shape", "added to three projects" | binds a number to the noun; states no total |
| `__pycache__` counted as a project | langchain-lab reported 6 against its stated 5 | p01..p05 is the whole set |
| A standard-library module read as a dependency | "no runtime dependencies (the DOM is built on `html.parser`)" | the sentence is saying the opposite |

That took it from 31 to 12. The remaining seven false positives are the table above.

### Its own flagship finding was not drift

The previous version of this section led with `agentic-ai-lab`'s README saying **zero
runtime dependencies** while its `pyproject.toml` declared 13 — and called it drift that
had appeared *during that session*, caught by running the tool rather than by constructing
an example.

It is not drift. The sentence is "In [`projects/`](projects). Zero runtime dependencies and
zero LLM calls", all eleven packages under that directory declare `dependencies = []`, and
the thirteen belong to the monorepo root's web layer, which the sentence never mentions.
Worse, the sentence splitter had already cut "In `projects/`" off as its own sentence, so
the scope was not in the text being adjudicated at all.

A repository whose sub-packages carry their own dependency lists cannot have a root-level
claim like that settled from the root `pyproject.toml`, so it is declined. The check still
runs on a repository of one package, and a test covers both.

Reproduce it:

```bash
cd 20_driftwatch
REPOS_ROOT=/path/to/your/checkouts python -m pytest tests/test_real_repos.py -q   # 17 passed
# The variable has to be on the pytest line. This block used to read
#   REPOS_ROOT=... \
#   cd 20_driftwatch && python -m pytest ...
# which sets it for `cd` and not for pytest - so the documented command produced the
# 17 SKIPPED it warned you about on the next line.
python -m pytest tests/test_structure.py -q                                       # 31 passed, 1 skipped
```

### Some claims are made by layout, not by a sentence

A heading reading `## All ten, at a glance` above a table of seven rows is drift, and the
sentence checker found **zero** checkable claims in the README containing it. The number is
in the heading, the noun it counts is nowhere, and the evidence is the table underneath.
`structure.py` reads that shape directly: a heading stating a count, checked against the
first table or list beneath it.

Across the same 76 repositories it finds **13 counted headings, all 13 correct**. That is a
small number and it is supposed to be — this checker's value is its precision, because the
first version reported **81.4% of them wrong** and every one of those was its own bug:

| False positive | Example | Why it isn't a count |
|---|---|---|
| Section indices | `## 04 · The injection that isn't an instruction` | a number, not a quantity |
| Dates | `## 2026-09-16 · three projects updated` | a date |
| Fenced code | `{"quote": "...12.4%"}` inside a ``` block | not a heading at all |
| Multi-line list items | a 3-item list whose items wrap | counted as 1 item |

Fixing those took the reported rate from 81.4% to 14.3%, and then to 0% once the one real
drift was fixed upstream. The sentence checker above went the same way twice, which is why
it is worth saying once more plainly: an 81% defect rate across other people's
repositories was never a finding about those repositories.

That one real drift is kept in [`tests/fixtures/code_llm_lab_drift.md`](tests/fixtures/code_llm_lab_drift.md),
copied verbatim from the commit that carried it. It was asserted against the live
repository until that README was rewritten by hand — at which point the test failed, for
the wrong reason. A test that depends on somebody else's file staying broken is not
evidence, so the evidence is now a fixture and the live check asserts only that the rate
stays believable.

## Agents and write authority

`agentplatform.authority` is default-deny, so a field nobody was granted is closed and a
column added next month does not quietly become writable. **The table is declared here and
the pipeline does not yet consult it**: no node passes an agent identity, so this is a
statement of who *should* write what, checked for coherence by a test, not a runtime
guard. It said "enforced" until an independent review grepped for a caller and found two,
both inside `authority.py` itself.

| Agent | May write | Never |
|---|---|---|
| `change-watcher` | `changes` from webhooks | a claim |
| `claim-extractor` | `claims` with a file and line | a verdict |
| `verifier` | `verdicts` — executed, never reasoned | a verdict on an unfalsifiable claim |
| `patch-writer` | `patches.draft` | committing |
| `pr-opener` | a pull request, on approval | merging |

## Architecture

| Topic | Carries |
|---|---|
| `drift.intake` | everything arriving from outside |
| `drift.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `drift.events` | the audit trail, and what the projector and SSE stream read |
| `drift.approvals` | an agent needs a person; resumes a checkpointed graph |
| `drift.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:delivery:{webhook_id}` | GitHub redelivers webhooks |
| `lock:repo:{id}` | one verification run per repository |
| `cache:facts:{sha}` | repository facts are re-derived per claim otherwise |
| `budget:{repo}:{day}` | a monorepo can exhaust a day of tokens |

**Postgres:** `repos, changes, claims, verdicts, patches, pulls, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Astro with React islands — a docs-shaped product deserves a docs-shaped site.

## Real data

35 real repositories and their real READMEs. `compliance-auditor` has already run over them and produced the figure this product starts from.

## The deterministic core

`src/driftwatch/domain.py` decides which documentation claims can be checked by running something, and which cannot. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 20_driftwatch
python -m pytest -q                      # 51 passed, 21 skipped
PYTHONPATH="src;../platform/src" python -m driftwatch.app    # console on http://127.0.0.1:8000
```

The 21 skips are the half that reads a folder of real git checkouts. `REPOS_ROOT` names
that folder and defaults to the one this repository sits in, so on the machine this was
written on all 72 run - and this line said "72 passed" for a while, a figure true on
exactly one computer. The number above is a fresh clone's, which is what a reader gets:
`REPOS_ROOT=/path/to/your/checkouts python -m pytest -q` runs the other 21.

`app.py` picks a model by capability rather than by tag — `models.resolve("general", …)`
returns the best one installed and records which it was, so a later run on a larger model
is a comparison row rather than an overwrite. The tests never reach a real model:
`llm.Recorded` raises on any prompt it was not scripted for.

## The graph

Seven nodes, built from `agentplatform.blueprint.review_pipeline`. The same seven every
product has; what differs is the judgement at each step, which lives in `agents.py`.

```
triage ──(early exit)──► exit ──► END
   │
   └─► gather (fan-out) ──► synthesise ──► compose ──► gate ──► approve ──► commit ──► END
        [alpha, beta]          [model]      [model]            [pauses]
```

`triage`, the early exit and `commit` are rules. Two nodes call the model. The gate drops
anything the model wrote that no tool receipt supports, before a person ever sees it.

## Scope

- **It does not merge.** It opens a pull request; a person merges.
- **It does not rewrite prose it cannot check.** An unfalsifiable claim is reported to a human, never silently edited.
- **It does not reason about a claim.** Mechanical claims are executed against the repository.
- **It does not replace `docstring-drift`.** That repository measured the phenomenon; this one repairs it.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `facts`, `issued_receipts`, `readme_claims`

Published to `drift.tasks`; the call returns `202 {"status": "pending"}` with queue lag
**1**. Nothing has touched the model at this point.

**Out** — after one worker pass:

| | |
|---|---|
| Status | `awaiting_approval`, paused at `approve` |
| Nodes visited | `triage` → `gather` → `synthesise` → `compose` → `gate` → `approve` |
| Model calls already spent | **2** |
| Claims kept by the gate | "Backed by a real receipt." |
| Claims dropped | "Asserted with nothing behind it." |
| Drop rate | 0.5 |

After `POST /approvals/{run}/approve`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `gather` → `synthesise` → `compose` → `gate` → `approve` → `commit` |
| Model calls | **2** — resuming added none |
| Result keys | `branch_status`, `branches`, `branches_failed`, `broken`, `claims`, `draft`, `drop_rate`, `dropped_claims`, `facts`, `issued_receipts`, `kept_claims`, `merged`, `model`, `patch.draft`, `readme_claims`, `summary`, `summary_subject`, `verifiable_share` |

**The early exit**, on a payload that trips `no_drift`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
