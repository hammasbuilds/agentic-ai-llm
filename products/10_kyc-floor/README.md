# 10 · kyc-floor

> Customer onboarding, sanctions and PEP screening, and triage of the alerts screening produces.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on OFAC's published sanctions list** — 19,393 entities, 7,535 individuals, and
**8,650 (primary name, alias) pairs that OFAC itself says are one party.** That is a
name-matching benchmark with real labels, on exactly the Arabic- and Urdu-origin names this
product exists for, requiring no annotation.

| Matcher | Recall, all pairs | Recall, matchable pairs | False positives | Alerts per screened name |
|---|---:|---:|---:|---:|
| Exact folded tokens | 27.8% | 33.4% | 0.005% | 1.0 |
| **+ consonant skeletons** | **44.9%** | **53.2%** | **0.005%** | **1.1** |
| ≥2 name parts in common | 62.6% | 73.7% | 0.055% | 6.0 |
| ≥1 name part in common | 87.5% | 99.7% | 1.74% | **148.6** |

**Folding consonant skeletons buys 19.8 points of recall and costs nothing.** Arabic script
does not write short vowels, so `zomor` / `zumar` / `zumur` / `zamur` are one name spelled
four ways by four transliterators; the false-positive rate does not move at all (1 hit in
20,000 random different-entity pairs, before and after).

**Past that, every point of recall is bought with precision, and the last stretch is
ruinous.** Loosening to "one name part in common" reaches 99.7% recall on matchable
aliases — and produces **148 alerts per screened name, worst case 855** against a
7,535-name list. A miss is a fine; that queue is unstaffable. The operational number, not
the recall number, is what picks the threshold.

**1,461 of the 8,650 pairs (16.9%) share no name part at all** — `ABBAS, Abu` and
`ZAYDAN, Muhammad` are one man. No spelling rule links a nom de guerre to a birth name, so
that fraction is a ceiling on string matching rather than a defect, and it is why the
"recall, all pairs" column can never reach 1.0.

## Checked against a second sanctions body

Every number above came off one list. A matching rule tuned on one authority's
transliteration habits is a rule about that authority — so the same code was run over the
**UN Security Council consolidated list**: 736 individuals, 2,163 graded alias pairs, a
different listing process and a different mix of regions.

| | OFAC | UN | |
|---|---:|---:|---|
| Recall over **all** labelled pairs, strict → skeletons | 27.8% → 44.9% | 14.7% → 25.7% | **+17.1 vs +11.0** |
| Recall over **reachable** pairs, strict → skeletons | 33.4% → 53.2% | 24.9% → 43.4% | **+19.8 vs +18.6** |
| Pairs no spelling rule can reach | 12.1% | **40.9%** | |
| False positives, skeletons, per 20,000 | 1 | 1 | |

**Measured over all pairs the two lists disagree by six points; measured over the pairs a
spelling rule could reach, they agree to within 1.2.** The disagreement was never about the
matcher. It was the denominator: a recall figure over all labels is partly a measurement of
how many unreachable labels the publisher happens to include, and the UN publishes far more
noms de guerre and single-word aliases than OFAC does. **That is a fact about the list, and
quoting it as a property of the matcher would have been wrong in both directions.**

### The UN can settle something OFAC cannot

OFAC publishes aliases ungraded. The UN marks each one `Good` or `Low`, where `Low` means
the UN itself is unsure the alias belongs to that person.

| Alias quality | n | Unreachable by any spelling rule |
|---|---:|---:|
| `Good` | 1,535 | 27.2% |
| **`Low`** | 628 | **74.4%** |

**Three quarters of the doubtful aliases are unreachable, against a quarter of the confident
ones.** The "unmatchable ceiling" this README has always claimed is a property of the labels
turns out to be exactly that, confirmed by the publisher's own confidence grade rather than
by argument.

### What did not transfer

The *ranking* of the rules is identical on both lists. The *thresholds* are not: "one name
part in common" costs 1.74% false positives on OFAC and **7.5% on the UN**, four times as
many, because these names are shorter and share common particles more often. A screening
threshold tuned on one list and shipped against another is a different product.


Reproduce it:

```bash
cd 10_kyc-floor && python -m pytest tests/test_real_sanctions.py -q     # 11 passed
cd 10_kyc-floor && python -m pytest tests/test_real_un.py -q            # 10 passed
```

### Two things that had to be fixed to get here

**Titles were being treated as name parts.** `AL ZAWAHIRI, Dr. Ayman` and
`AL-ZAWAHIRI, Ayman Muhammad Rabi` failed to match on `dr` alone.

**Subset matching is the wrong rule when both sides carry extra parts.** Requiring every
token of one name to appear in the other fails the moment each spelling adds something the
other lacks — which is the normal case on a sanctions list, not the exception.

## Agents and write authority

`agentplatform.authority` is default-deny, so a field nobody was granted is closed and a
column added next month does not quietly become writable. **The table is declared here and
the pipeline does not yet consult it**: no node passes an agent identity, so this is a
statement of who *should* write what, checked for coherence by a test, not a runtime
guard. It said "enforced" until an independent review grepped for a caller and found two,
both inside `authority.py` itself.

| Agent | May write | Never |
|---|---|---|
| `doc-verifier` | `identity.fields` with confidence | an approval |
| `name-matcher` | `screening_hits` — deterministic | a disposition |
| `alert-triager` | `alerts.disposition`, clear false positives only | clearing a true match |
| `media-researcher` | `media_findings` with source and date | an unsourced allegation |
| `filing-writer` | `sar.draft` | filing |
| `qa-sampler` | `qa_reviews` | overriding a human |

## Architecture

| Topic | Carries |
|---|---|
| `kyc.intake` | everything arriving from outside |
| `kyc.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `kyc.events` | the audit trail, and what the projector and SSE stream read |
| `kyc.approvals` | an agent needs a person; resumes a checkpointed graph |
| `kyc.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:{customer}:{list_version}` | a daily list refresh re-screens the whole book |
| `lock:alert:{id}` | one triager per alert |
| `index:names` | the in-memory screening index |
| `live:sla` | alert-ageing counters against the SLA |

**Postgres:** `customers, documents, identities, list_versions, screening_hits, alerts, media_findings, filings, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Next.js App Router — an alert queue, a four-quadrant match view, a filing composer.

## Real data

The **OFAC SDN list**, the **UN Consolidated Sanctions List** and the **EU list** — all publicly downloadable, all carrying alias fields, all full of the Arabic- and Urdu-origin names `urdu-nlp-toolkit` was written for.

## The deterministic core

`src/kycfloor/domain.py` decides whether two spellings are the same name. Nothing about that is language understanding; it is normalisation. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 10_kyc-floor
python -m pytest -q                      # 39 passed
PYTHONPATH="src;../platform/src" python -m kycfloor.app    # console on http://127.0.0.1:8000
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

- **It does not onboard a customer.** It screens and triages; a human approves.
- **It does not clear a true match.** The triager may dispose of clear false positives and nothing else.
- **It does not file a SAR.** Draft only.
- **It does not score risk with a model.** A published matrix, so a regulator can read it.
- **It does not match names with an LLM.** That is the baseline it is measured against, not the implementation.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `issued_receipts`, `listed`, `name`

Published to `kyc.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `draft`, `drop_rate`, `dropped_claims`, `filed`, `hit_count`, `hits`, `issued_receipts`, `kept_claims`, `listed`, `model`, `name`, `sar.draft`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `cleared`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
