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

**Measured over every repository in a real folder of checkouts, full history** — 74
checkouts, 1,222 commits, 1,601,517 line edits, frozen on 2026-10-05 as
[`tests/fixtures/portfolio_survey.json`](tests/fixtures/portfolio_survey.json). Every number
below is read from that fixture and asserted in
[`tests/test_real_reverts.py`](tests/test_real_reverts.py), so the two cannot drift apart.

It used to be measured live, and that is why the fixture exists. The disk is a working
machine several sessions commit to, so the totals moved under the tests: `authored_reverts
== 27` broke first, then the median revert gap, then the share of repositories with none,
then the rate band itself. Each break was a property of the disk that afternoon rather than
of the method, and widening a band every time is a moving target, not a measurement.

| | Naive | Authored | **Code** |
|---|---:|---:|---:|
| Line edits counted | 1,601,517 | 589,024 | **372,794** |
| Reverts found | 1,850 | 138 | **46** |
| **Revert rate** | 0.1155% | 0.0234% | **0.0123%** |
| | | | *one in 8,104* |

**The same history, read three ways, differs by an order of magnitude** — 9.36× between the
first column and the last. The gap is not a detail of the corpus. It is two decisions about
what counts as an edit, and both are decisions this product has to make on a CRM where
agents and people write into the same records.

**1. Machine-written files are most of the edits and 92.5% of the reverts.** Committed
datasets and regenerated `results.json` files are not somebody's judgement. A number
returning to a previous value across re-runs is a script re-emitting its own output, not one
writer undoing another. Committed CSV, TXT, LOG and GenBank data dilute the denominator from
the other end at the same time.

**2. A line removed and restored inside one commit never moved.** With `-U0` git reports a
line that shifted within a file as a remove/add pair. Reading that as a revert accounted for
**86%** of what remained. Undoing is a relationship *between* commits, so same-commit pairs
cancel and the three events must land on three increasing commits.

**3. "Authored" was not a fine enough cut, and finding that out is the newest result here.**
As the corpus grew from 36 repositories to 74 the authored rate more than doubled, 0.0101%
to 0.0234% — and nobody started undoing their own work twice as often. 92 of the 138 authored
reverts are **prose**: a README line returning verbatim while whole tables are rewritten in
bulk is a line being restated, not one writer overruling another. `is_authored` separates a
person from a script; it does not separate a decision from a restatement, and only code makes
that distinction cleanly, because a line of prose has no behaviour to undo. The prose rate is
0.0425%, three and a half times the code rate.

What survives is small and real: **46 reverts in 372,794 lines of hand-written code**, median
gap 6 commits, maximum 44, and **42 of the 59 repositories with substantial code contain none
at all**. The code rate also sat inside the band measured at half this corpus size, which is
the only reason to believe it: the claim survived the portfolio doubling once the denominator
was right. That is the floor a medium with diffs, atomic commits and review achieves — and it
is the useful number precisely because a CRM field has none of them. No diff is shown, no
commit is atomic, nothing is reviewed, and the writer is often a process rather than a
person.

### The distinction proved itself by accident, twice

**At 36 repositories.** Halfway through this work, `agri-desk`'s corpus was replaced with a
7.5 MB GenBank file committed to this repository — about **127,000 new line edits**, none of
them written by a person.

| Reading taken at 36 repos | Before | After the commit | After a 36th repo appeared |
|---|---:|---:|---:|
| Naive rate | 0.1489% | 0.1222% | 0.1217% |
| Authored rate | 0.0102% | 0.0102% | 0.0101% |
| Authored reverts | 27 | 27 | 27 |

An 18% swing in the headline, caused by no change in how anybody edits anything, while the
authored rate did not move at all.

**At 74 repositories, it happened again and went further.** The corpus doubled, and this time
the *authored* rate moved too — 0.0101% to 0.0234% — because the portfolio's Markdown grew
faster than its code and 92 of 138 authored reverts are prose. The **code** rate landed at
0.0123%, inside the band measured at half the size. So the same argument had to be made one
level in: separating a person from a script was not enough, and separating a decision from a
restatement was.

A metric that reacts to someone committing a dataset is not measuring editing behaviour, and
on a CRM the equivalent commit — a bulk enrichment import — happens weekly. The current
numbers are in the table at the top of this file, read from the frozen fixture; the two
readings above are kept because the *drift* is the finding, and deleting them would delete
the evidence for the distinction the product rests on.

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
cd 01_revenue-desk && python -m pytest tests/test_real_reverts.py -q     # 18 passed
```

## Agents and write authority

`agentplatform.authority` is default-deny, so a field nobody was granted is closed and a
column added next month does not quietly become writable. **The table is declared here and
the pipeline does not yet consult it**: no node passes an agent identity, so this is a
statement of who *should* write what, checked for coherence by a test, not a runtime
guard. It said "enforced" until an independent review grepped for a caller and found two,
both inside `authority.py` itself.

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

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Angular 19 — pipeline board, per-deal timeline showing which agent wrote which field, approvals queue, forecast page.

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
python -m pytest -q                      # 38 passed, 1 skipped
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

`triage`, the early exit and `commit` are rules. Two nodes call the model.

The gate drops any claim whose receipts were not issued, before a person ever sees it -
and it reports where the claims came from, because that decides what the number means.
This paragraph used to read "drops anything the model wrote that no tool receipt
supports", which is not what happens: no node here writes `claims` or
`issued_receipts`, both arrive in the request body (they are in the input keys below),
and the two model nodes write `summary` and `draft`, which the gate never reads. So the
filtering is a real audit of a draft the caller supplied, and `drop_rate` is `null`
rather than a figure, because a rate over the caller's own input is not a measurement of
the model.

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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `draft.body`, `drop_rate`, `dropped_claims`, `issued_receipts`, `iterations`, `kept_claims`, `lead.score`, `lead.stage`, `model`, `receipts_source`, `reply`, `reply.intent`, `sent`, `signals`, `summary` |

**The early exit**, on a payload that trips `suppressed`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `classify` → `suppress` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
