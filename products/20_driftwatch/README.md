# 20 · driftwatch

> Watches a repository for the moment its documentation stops being true, and opens the pull request that fixes it.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured over 35 real repositories** — their real READMEs, real
`pyproject.toml` files and real directory contents.

| | |
|---|---:|
| Candidate claims (README sentences) | **4,757** |
| Claims a machine can adjudicate | **78** (1.64%) |
| Of those, claims with a fact to check against | 55 (70.5%) |
| Claims that were checked and are **false** | **5** (9.1% of checked) |

**Fewer than two sentences in a hundred can be settled by a checker.** Doc-linting tools
are built as though that fraction were most of the file, which is why they produce a wall
of unfalsifiable findings and get switched off in week two. The other 98.4% is prose: it
may be wrong, but no tool is going to be the thing that decides.

The five that are false are real drift, found live:

| Repository | Drift |
|---|---|
| `agentic-ai-lab` | README says **zero runtime dependencies**; `pyproject.toml` declares 13, including fastapi, redis, aiokafka and langgraph |
| `classical-computer-vision` | README says **41 projects**; there are **57** |
| `rag-forge` (x2) | references `RESULTS.md`, which does not exist |
| `sql-analyst-agent` | references `RESULTS.md`, which does not exist |

The first of those drifted **during this session**: the dependencies were added by other
work in the same repository while the README kept its old claim. That is exactly the moment
this product exists to catch, and it was caught by running the tool rather than by
constructing an example.

Note the middle row too. Almost a third of the mechanically-shaped claims could not be
checked because no fact answered them — a claim being *checkable in principle* and a
checker *having the fact* are different things, and conflating them inflates the headline.

Reproduce it:

```bash
cd 20_driftwatch && python -m pytest tests/test_real_repos.py -q     # 10 passed
cd 20_driftwatch && python -m pytest tests/test_structure.py -q     # 11 passed
```

### What had to be fixed to get this number

The first extractor treated every sentence as a claim and reported 4,757 findings, nearly
all of them unfalsifiable adjectives. Classification has to come before verification, or
the output is noise with five real defects buried in it.

### Some claims are made by layout, not by a sentence

A heading reading `## All ten, at a glance` above a table of seven rows is drift, and the
sentence checker found **zero** checkable claims in the README containing it. The number is
in the heading, the noun it counts is nowhere, and the evidence is the table underneath.
`structure.py` reads that shape directly: a heading stating a count, checked against the
first table or list beneath it.

Across the same 35 repositories it finds **6 counted headings, all 6 correct**. That is a
small number and it is supposed to be — this checker's value is its precision, because the
first version reported **81.4% of them wrong** and every one of those was its own bug:

| False positive | Example | Why it isn't a count |
|---|---|---|
| Section indices | `## 04 · The injection that isn't an instruction` | a number, not a quantity |
| Dates | `## 2026-09-16 · three projects updated` | a date |
| Fenced code | `{"quote": "...12.4%"}` inside a ``` block | not a heading at all |
| Multi-line list items | a 3-item list whose items wrap | counted as 1 item |

Fixing those took the reported rate from 81.4% to 14.3%, and then to 0% once the one real
drift was fixed upstream. **A checker whose first output is an alarming rate is usually
measuring itself.**

That one real drift is kept in [`tests/fixtures/code_llm_lab_drift.md`](tests/fixtures/code_llm_lab_drift.md),
copied verbatim from the commit that carried it. It was asserted against the live
repository until that README was rewritten by hand — at which point the test failed, for
the wrong reason. A test that depends on somebody else's file staying broken is not
evidence, so the evidence is now a fixture and the live check asserts only that the rate
stays believable.

## Agents and write authority

Enforced by `agentplatform.authority`, which is default-deny — a field nobody was granted
is closed, so a column added next month does not quietly become writable.

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

**UI:** Astro with React islands — a docs-shaped product deserves a docs-shaped site.

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
python -m pytest -q                      # 41 passed
PYTHONPATH="src;../platform/src" python -m driftwatch.app    # console on http://127.0.0.1:8000
```

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
