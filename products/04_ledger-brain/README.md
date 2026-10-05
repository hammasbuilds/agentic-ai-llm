# 04 · ledger-brain

> SME back office: invoices in, bank statements in, reconciliation, inventory and cash flow out.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on 54,716 real invoices** from UCI's Online Retail II, reduced once to invoice
totals by `scripts/make_invoices.py`.

Restricted to receivables — positive totals, the invoices someone is expected to pay:

| | |
|---|---:|
| Invoices | 40,912 |
| **Sharing their exact amount with another invoice** | **20,817 (50.9%)** |
| Distinct amounts that collide | 7,006 |
| Largest collision | **126 invoices at £15.00** |
| Accuracy of an amount-only matcher **on the colliding half** | **33.7%** |
| Headline accuracy across the whole population | 66.3% |

**Half of real invoices cannot be identified by their amount.** This is not a tail or an
edge case; it is half the book.

The two accuracy figures are the point. 66% looks like a matcher that mostly works and
needs a little polish. It is the average of *always right on the unique half* and *wrong
two times in three on the other half* — and only the second half does any damage, because
a wrong match moves real money against the wrong customer's account. Splitting the metric
by the equal-amount subset is what makes the problem visible; the headline is what hides it.

So the matcher refuses. Two open invoices at the same amount produce an `ambiguous` result
and a question, never a choice.

### An artefact worth naming

**5,372 invoices total exactly £0.00** — cancellations whose line items net out. Every one
collides with every other, which pushes the all-invoice collision rate to 59.9%. Leaving
them in would have made the finding look stronger and would have been wrong: they are a
different reconciliation problem. The receivables-only figure is the one quoted above, and
both are in the tests.

Reproduce it:

```bash
python scripts/make_invoices.py                                       # once, needs openpyxl
cd 04_ledger-brain && python -m pytest tests/test_real_invoices.py -q  # 10 passed
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
| `doc-intake` | `documents`, extracted fields with per-field confidence | a posted transaction |
| `reconciler` | `matches` where the deterministic matcher is unambiguous | an ambiguous match |
| `match-explainer` | `matches.rationale` | `matches.decision` |
| `inventory-watcher` | `reorder_suggestions` | a purchase order |
| `cashflow-analyst` | `projections` (computed) | a figure it did not compute |
| `collections-writer` | `chase_drafts` | sending |

## Architecture

| Topic | Carries |
|---|---|
| `fin.intake` | everything arriving from outside |
| `fin.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `fin.events` | the audit trail, and what the projector and SSE stream read |
| `fin.approvals` | an agent needs a person; resumes a checkpointed graph |
| `fin.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:doc:{sha256}` | the same invoice is photographed twice, constantly |
| `lock:invoice:{id}` | one reconciler per invoice |
| `cache:fx:{pair}:{day}` | rates are fetched once a day, not per row |
| `live:cash_position` | the dashboard figure |

**Postgres:** `documents, invoices, payments, matches, items, stock_moves, projections, events` — `events` is an immutable ledger of every posting.

**UI:** Django 5 + Tailwind, server-rendered — the right shape for a bookkeeping product, and the only server-rendered UI here.

## Real data

UCI Online Retail II for transaction history (a different angle from `csv-analyst`: inventory and cash flow, not revenue analysis), plus real invoice formats through `doc-intelligence-api`, which already parses CNIC, NTN, STRN and PK IBAN.

## The deterministic core

`src/ledger/domain.py` decides which payments match which invoices, and which matches are too ambiguous to make. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 04_ledger-brain
python -m pytest -q                      # 27 passed
PYTHONPATH="src;../platform/src" python -m ledger.app    # console on http://127.0.0.1:8000
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

- **It does not post a journal entry on its own.** Every posting is a human action.
- **It does not let a model do arithmetic.** Numbers are computed in Python and quoted verbatim; a response containing a numeral absent from the tool output is rejected.
- **It does not guess between equal amounts.** It refuses and asks, which is the whole design.
- **It is not accounting software.** It reconciles and explains; it does not file anything.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `invoices`, `issued_receipts`, `payments`

Published to `fin.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `ambiguous`, `branch_status`, `branches`, `branches_failed`, `chase.draft`, `claims`, `draft`, `drop_rate`, `dropped_claims`, `invoices`, `issued_receipts`, `kept_claims`, `matched`, `model`, `payments`, `sent`, `summary`, `summary_subject`, `unmatched` |

**The early exit**, on a payload that trips `refused`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
