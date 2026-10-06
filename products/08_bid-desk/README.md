# 08 · bid-desk

> Tender discovery, bid or no-bid, a compliance checklist that cannot be soft-passed, and a proposal drafted from work you won.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

Public tender portals do not publish machine-readable requirement labels, so the mandatory
/ optional distinction is measured where it *is* labelled: **published RFCs**. RFC 2119
defines which words make a requirement binding and states that they count **only in upper
case** — so `MUST` is an obligation and `must` in the next sentence is prose. That is
ground truth with no annotation, in documents where missing a mandatory item genuinely
means rejection.

Across the twenty-four RFCs in [`products/data/`](../data):

| | |
|---|---:|
| Requirements (RFC 2119, upper case) | 4,304 |
| Of those, mandatory (`MUST`, `MUST NOT`, `SHALL`, `REQUIRED`) | 2,389 |
| What a case-insensitive reader finds | 6,143 |
| **Recall on mandatory items** | **1.000** |
| **Precision** | **0.825** |
| **False positives** | **501** |

Measured on six RFCs, then seventeen, now twenty-four. Precision went 0.830 → 0.827 →
0.825: five thousandths across a corpus four times the size, which is the reason to
believe it rather than the first number.

The table said "seventeen" and 4,036 / 2,242 / 5,750 / 465 until this was re-run.
`rfc._documents()` globs `rfc*.txt`, so adding files to the shared corpus moved every
figure and the prose did not follow - and the test that guards the headline used
`approx(0.827, abs=0.015)`, a band wide enough to hold 0.812 through 0.842, so it
absorbed the drift without a word. Its own docstring already recorded "0.825 over
twenty-four".

### This reverses the asymmetry this README predicted

The stated design argument was that *a miss is fatal and a false positive costs ten
minutes*, so the extractor should be tuned for recall. Measured, **recall is not the
problem**: upper case is a subset of case-insensitive, so a naive reader cannot miss a
binding clause. It cannot miss, and it over-reports by twenty per cent.

One flagged obligation in five is not one. A compliance checklist built by reading for the
word "must" carries 501 phantom requirements, and a bid team works through every one of
them — costing time, and worse, **over-scoping the bid** against obligations nobody imposed.

So the guard that matters here is the opposite of the one originally designed: the checklist
must be able to say *this is not a requirement*, and the signal it needs — the capital
letters — is exactly what a case-insensitive reader throws away.

The general lesson transfers to tenders directly. "Shall provide" in a scope narrative and
"SHALL provide" in a compliance schedule are different objects, and whatever distinguishes
them in a given portal's formatting is the thing an extractor must not normalise away.

Reproduce it:

```bash
cd 08_bid-desk && python -m pytest tests/test_real_requirements.py -q     # 11 passed
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
| `crawler` | `tenders` (raw, plus a source snapshot) | a parsed requirement |
| `requirement-extractor` | `requirements`, each with a source span | an inferred requirement |
| `fit-scorer` | `fit_scores` from rules and a capability matrix | the bid/no-bid decision |
| `competitor-analyst` | `market_notes` with source dates | an undated claim |
| `proposal-writer` | `proposal_sections` | a capability claim absent from the capability store |
| `compliance-checker` | `checklist` pass or fail per item | a soft pass |

## Architecture

| Topic | Carries |
|---|---|
| `bid.intake` | everything arriving from outside |
| `bid.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `bid.events` | the audit trail, and what the projector and SSE stream read |
| `bid.approvals` | an agent needs a person; resumes a checkpointed graph |
| `bid.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:tender:{reference}` | the same tender is listed on three portals |
| `crawl:{domain}` | per-domain politeness, not a global rate |
| `lock:tender:{id}` | one extraction run per tender |
| `cache:fetch:{url}` | portals are slow and re-fetched across agents |

**Postgres:** `tenders, requirements, fit_scores, capabilities, proposal_sections, checklists, market_notes, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Flutter Web — a deadline board that also works on a phone, which is what a bid manager actually needs.

## Real data

**PPRA** public tenders (Pakistan), plus **TED** (EU) and **SAM.gov** (US) — all openly published with structured feeds.

## The deterministic core

`src/biddesk/domain.py` decides whether a bid is submittable at all, and how many days are left. Both are counting, not judgement. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 08_bid-desk
python -m pytest -q                      # 27 passed
PYTHONPATH="src;../platform/src" python -m biddesk.app    # console on http://127.0.0.1:8000
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

- **It does not submit.** Submission is a human action, every time.
- **It does not soft-pass a mandatory item.** Missing is missing; the bid is blocked.
- **It does not claim a capability you cannot evidence.** Unbacked claims are dropped before drafting.
- **It does not cite an undated source.** Stale market numbers reported as current is the standard failure of this category.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `evidenced`, `issued_receipts`, `requirements`, `tender`

Published to `bid.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `draft`, `drop_rate`, `dropped_claims`, `evidenced`, `issued_receipts`, `kept_claims`, `missing_mandatory`, `model`, `receipts_source`, `requirements`, `section.draft`, `submittable`, `submitted`, `summary`, `summary_subject`, `tender` |

**The early exit**, on a payload that trips `blocked`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
