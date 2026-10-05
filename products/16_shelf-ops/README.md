# 16 · shelf-ops

> Marketplace operations: catalogue, repricing, promotions, returns triage and supplier chasing, with one price authority.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on 4,501 real products** from UCI Online Retail II, each with the modal,
minimum, maximum and median price it actually transacted at.

### A product does not have a price

| | |
|---|---:|
| Median observed range, as a multiple of the modal price | **1.29x** |
| 90th percentile | 2.63x |
| Products ever sold below their own modal price | **78.7%** |

The median product's price range is wider than its own usual price. A repricing agent is
not setting *the* price; it is moving inside a distribution that is already wide.

### Two agents, each individually correct

Taking the floor to be **the lowest price that product ever actually sold at** — evidence
rather than an assumption, because the business demonstrably accepted it — and running one
repricer at 10% against one promotions agent at 15%:

| Policy | Products priced below their own historic floor |
|---|---:|
| One price authority, deepest discount applied | 1,883 (41.8%) |
| Two agents, discounts compounding | 2,792 (62.0%) |
| **Attributable to compounding alone** | **909 (20.2%)** |

**Compounding breaks one product in five**, and neither agent did anything wrong. 10% is
within policy. 15% is within policy. 23.5% is not a policy anyone wrote.

No prompt fixes this, because there is no prompt to fix: both agents behaved correctly and
the system did not. The fix is structural — agents propose, and exactly one component
writes the price.

**Context worth stating:** 41.8% of products fall below that floor on a single 15% discount
alone, because "the lowest price ever transacted" is an aggressive floor that includes
clearance. The number attributable to compounding is the marginal 20.2%, and that is the one
this product is about.

Reproduce it:

```bash
python scripts/make_prices.py                                       # once, needs openpyxl
cd 16_shelf-ops && python -m pytest tests/test_real_catalogue.py -q  # 9 passed
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
| `listing-writer` | `listings.draft` | a published listing |
| `repricer` | `price_proposals` | `listings.price` directly |
| `promotions-planner` | `price_proposals` | `listings.price` directly |
| `price-authority` | `listings.price` — the only writer, deterministic | going below the floor |
| `returns-classifier` | `returns.reason` | issuing a refund |
| `supplier-chaser` | `chase_drafts` | sending |

## Architecture

| Topic | Carries |
|---|---|
| `shelf.intake` | everything arriving from outside |
| `shelf.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `shelf.events` | the audit trail, and what the projector and SSE stream read |
| `shelf.approvals` | an agent needs a person; resumes a checkpointed graph |
| `shelf.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:sku:{id}` | per-SKU ordering, which is why the bus is keyed on SKU |
| `cache:competitor:{sku}` | competitor prices are polled, not fetched per proposal |
| `idem:order:{marketplace}:{id}` | marketplaces redeliver order webhooks |
| `live:margin` | the board's realised-margin counter |

**Postgres:** `skus, listings, price_proposals, price_history, orders, returns, suppliers, events`.

**UI:** SolidStart, or an Electron workstation for a warehouse desk that is open all day.

## Real data

UCI Online Retail II for order history, and published marketplace fee schedules, which are real and openly available. Competitor prices are polled from sites that permit it.

## The deterministic core

`src/shelfops/domain.py` decides the final price, from every proposal at once, with a hard floor. Discounts never compound. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 16_shelf-ops
python -m pytest -q                      # 27 passed
PYTHONPATH="src;../platform/src" python -m shelfops.app    # console on http://127.0.0.1:8000
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

- **It does not let an agent write a price.** Agents propose; one deterministic authority decides.
- **It does not compound discounts.** The deepest single proposal wins and the floor is absolute.
- **It does not issue refunds.** Returns are classified and routed.
- **It does not scrape a marketplace that forbids it.** Feeds and APIs where they exist.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `base`, `claims`, `cost`, `fee_pct`, `floor`, `issued_receipts`, `proposals`

Published to `shelf.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `applied_by`, `at_floor`, `base`, `branch_status`, `branches`, `branches_failed`, `claims`, `cost`, `draft`, `drop_rate`, `dropped_claims`, `fee_pct`, `floor`, `issued_receipts`, `kept_claims`, `listing.price`, `margin`, `model`, `note`, `price`, `proposals`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `held_at_floor`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
