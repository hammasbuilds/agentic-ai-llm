# 01 · revenue-desk

> Multi-agent CRM and lead engine whose forecast is arithmetic and whose agents cannot overwrite you.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

This product exists to measure how often one writer's update destroys another's recent
correction. There is no real CRM log available to measure that on — so rather than invent
one, the same *mechanism* is measured on the largest real corpus of dated edits available:
**the git history of the repositories on this disk.**

A revert is a line that went A, then B, then back to A. Not a rewrite, not churn — one edit
undoing another, which is exactly what `detect_reverts` looks for on a deal record.

**Measured over every repository in a real folder of checkouts, full history** — 36 checkouts, 429
commits, 714,164 line edits. This is a live disk: the totals move as other work lands on it,
which turns out to be the point.

| | Naive | **Honest** |
|---|---:|---:|
| Line edits counted | 714,164 | **267,192** |
| Reverts found | 869 | **27** |
| **Revert rate** | 0.1217% | **0.0101%** |
| | | *one in 9,896* |

**The same history, read two ways, differs by an order of magnitude.** The gap is not a
detail of the corpus — it is two decisions about what counts as an edit, and both of them
are decisions this product has to make on a CRM where agents and people write into the same
records.

**1. Machine-written files are most of the edits and 97% of the reverts.** Committed datasets
and regenerated `results.json` files are not somebody's judgement. Every one of the 1,457
reverts in JSON came from 13 result files — `mcp-lab/projects/03_bfcl_tool_calling/results.json`
alone contributed 553. A number returning to a previous value across re-runs is a script
re-emitting its own output, not one writer undoing another. Committed CSV, TXT, LOG and
GenBank data contributed **over 300,000 edits and zero reverts**, quietly diluting the
denominator at the same time.

**2. A line removed and restored inside one commit never moved.** With `-U0` git reports a
line that shifted within a file as a remove/add pair. Reading that as a revert accounted for
**86%** of what remained. Undoing is a relationship *between* commits, so same-commit pairs
now cancel and the three events must land on three increasing commits.

What survives is small and real: **27 reverts in 267,192 hand-written line edits**, median
gap one commit, maximum 23. **29 of the 35 substantial repositories contain none at all.**
That is the floor a medium with diffs, atomic commits and review achieves — and it is the
useful number precisely because a CRM field has none of them. No diff is shown, no commit is
atomic, nothing is reviewed, and the writer is often a process rather than a person.

### The distinction proved itself by accident

Halfway through this work, `agri-desk`'s corpus was replaced with a 7.5 MB GenBank file
committed to this repository — about **127,000 new line edits**, none of them written by a
person.

| | Before | After the commit | After a 36th repo appeared |
|---|---:|---:|---:|
| Naive rate | 0.1489% | 0.1222% | **0.1217%** |
| Honest rate | 0.0102% | 0.0102% | **0.0101%** |
| Authored reverts | 27 | 27 | **27** |

**An 18% swing in the headline, caused by no change in how anybody edits anything** — and
then a whole new repository arrived and the honest rate still did not move. The
authored rate did not move at all. A metric that reacts to someone committing a dataset is
not measuring editing behaviour, and on a CRM the equivalent commit — a bulk enrichment
import — happens weekly. There is a test pinning both halves of this.

### What is not claimed

**The agent-versus-human revert rate in a CRM is not measured here**, because no such log
was available. What is established is the floor, the detector, and the fact that
the detector finds real reverts in real history rather than only in fixtures. The product's
provenance mechanism — field-level ownership, an agent allowed to propose but not overwrite
a human-owned field — is built because you cannot reach that floor without controls, not
because a number here proves a CRM is worse.

Saying so is the point. A README claiming a measured CRM revert rate would be claiming a
measurement that was never made.

### Three things the tests caught

- `find_reverts` originally relied on the git parser to skip trivial lines, so a caller
  building edits directly could get a closing brace reported as a revert. Whether a line is
  substantial enough to count is a property of revert detection, not of where the edits came
  from, and it now lives there.
- **The survey was capped at 12 repositories, in name order.** That reported 0.0237% against
  0.1222% over all 35 — a fivefold undercount, because the repositories with the most
  regenerated result files, `mcp-lab` and `nlp-lab` with 1,343 reverts between them, sort
  after the twelfth. **But the authored rate moves the other way**: 24 of the 27 hand-written
  reverts are inside those first twelve, so the subset slightly *overstates* it. A
  convenience cut has no reliable direction — which is the argument for removing it rather
  than reasoning about which way it leans. Both directions are now pinned by a test.
- The corrections pull against each other, which is why none was noticed for so long.
  Widening the corpus raised the naive number fivefold; excluding generated files and
  same-commit pairs cut it by an order of magnitude. The old assertions were loose bands
  (`< 0.005`, `> 50`) and passed comfortably throughout.

Reproduce it:

```bash
cd 01_revenue-desk && python -m pytest tests/test_real_reverts.py -q     # 13 passed
```

## Agents and write authority

Enforced by `agentplatform.authority`, which is default-deny — a field nobody was granted
is closed, so a column added next month does not quietly become writable.

| Agent | May write | Never |
|---|---|---|
| `scout` | `leads` (new rows) | an existing lead's fields |
| `enricher` | `company.*` facts, each with a source URL | anything on a deal |
| `qualifier` | `lead.score`, `lead.stage` (rules-derived) | a stage jump greater than one |
| `writer` | `drafts` | `messages` — it never sends |
| `reply-classifier` | `reply.intent`, `contact.opted_out` | clearing an opt-out |
| `deal-analyst` | `deal.risk_factors` | `deal.amount`, `deal.close_date` — proposes only |
| `forecaster` | nothing; it reads | every field |

## Architecture

| Topic | Carries |
|---|---|
| `crm.intake` | everything arriving from outside |
| `crm.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `crm.events` | the audit trail, and what the projector and SSE stream read |
| `crm.approvals` | an agent needs a person; resumes a checkpointed graph |
| `crm.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:gmail:{message_id}` | mail providers redeliver, constantly |
| `lock:deal:{id}` | two agents must never write one deal at once |
| `budget:{mailbox}:{day}` | a token ceiling that is also a deliverability control |
| `llmcache:{sha}` | enrichment prompts repeat across a sequence |

**Postgres:** `accounts, contacts, deals, activities, drafts, suppression, agent_runs, approvals, events` — with a provenance column on every agent-writable field.

**UI:** Angular 19 — pipeline board, per-deal timeline showing which agent wrote which field, approvals queue, forecast page.

## Real data

A local file of mined hiring posts (`extracted.jsonl`, not published) — 247 records already mined from 286 hiring-post screenshots. Companies hiring AI engineers *are* the lead list. Plus the SECP public register and OpenCorporates.

## The deterministic core

`src/revenue/domain.py` decides the forecast figure and which agent edits are reverts. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 01_revenue-desk
python -m pytest -q                      # 34 passed
PYTHONPATH="src;../platform/src" python -m revenue.app    # console on http://127.0.0.1:8000
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

- **It does not send.** The writer agent produces drafts; sending is a human action behind an approval.
- **It does not scrape a platform that forbids it.** Sources are search, public registers and sites that permit crawling.
- **It does not score a lead with a model.** Fit is a rules-and-weights calculation the buyer can read.
- **It does not resolve a provenance conflict.** It surfaces one and stops.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `issued_receipts`, `reply`, `signals`

Published to `crm.tasks`; the call returns `202 {"status": "pending"}` with queue lag
**1**. Nothing has touched the model at this point.

**Out** — after one worker pass:

| | |
|---|---|
| Status | `awaiting_approval`, paused at `approve` |
| Nodes visited | `classify` → `qualify` → `enrich` → `synthesise` → `draft` → `gate` → `approve` |
| Model calls already spent | **2** |
| Claims kept by the gate | "They are hiring three AI engineers." |
| Claims dropped | "They are evaluating vendors this quarter." |
| Drop rate | 0.5 |

After `POST /approvals/{run}/approve`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `classify` → `qualify` → `enrich` → `synthesise` → `draft` → `gate` → `approve` → `send` |
| Model calls | **2** — resuming added none |
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `draft.body`, `drop_rate`, `dropped_claims`, `issued_receipts`, `iterations`, `kept_claims`, `lead.score`, `lead.stage`, `model`, `reply`, `reply.intent`, `sent`, `signals`, `summary` |

**The early exit**, on a payload that trips `suppressed`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `classify` → `suppress` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
