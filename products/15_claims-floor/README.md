# 15 · claims-floor

> Insurance claims from first notice to settlement pack, against the policy wording that was actually in force.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on real versioned regulation across six regulators** — eCFR version indexes for
Titles 12, 21, 26, 29, 40 and 45: 6,000 real section versions across 3,204 sections, each
with the date its amendment took effect.

| | |
|---|---:|
| Sections | 3,204 |
| **Amended more than once** | **1,342 (42%)** |
| Median versions per amended section | 2 (max 26) |
| Questions where the date matters | 4,138 |
| **Answered wrongly by returning the current text** | **2,032 (49.1%)** |
| **Median staleness of the returned text** | **2.47 years** |
| Worst case | **10.0 years** |

**For a section that has ever been amended, answering from the current text answers a
different question half the time.** The answer is fluent, it cites a real section, and it is
about a different set of words than the one that governed the event.

### One regulator is one drafting culture

This was first measured on Title 29 alone, and one of its two headline numbers did not
survive contact with the other five.

| Title | | Amended | Wrong-version rate | Median staleness |
|---:|---|---:|---:|---:|
| 26 | Internal Revenue | 312 | 0.209 | 2.63 yr |
| 21 | Food & Drugs | 174 | 0.421 | 3.64 yr |
| 45 | Public Welfare | 196 | 0.448 | 4.35 yr |
| 29 | **Labor** | 272 | **0.522** | **0.28 yr** |
| 12 | Banks | 213 | 0.546 | 2.55 yr |
| 40 | Environment | 175 | 0.743 | 1.99 yr |

**The rate generalised. The severity did not.** Title 29's 52.2% sits mid-range against a
pooled 49.1%, so the headline was sound. But its median staleness of **0.28 years** is a
tenth of every other regulator's, and the old README explained that away in a sentence:
*"the median gap is under a year, because most amendments are recent."* That was a fact
about OSHA presented as a fact about versioned documents. Pooled across six titles the
median error is **2.47 years** — not a tail risk, the typical case.

The rate itself still varies three and a half fold, from Tax at 0.209 to the EPA at 0.743.
A product that quotes one number for "how often this matters" is quoting a number about
whichever regulator it happened to read.

So the product refuses rather than defaults. A loss date with no wording in force raises
`NoVersionInForceError`; overlapping versions raise too. Falling back to the latest was the
first behaviour written here and is exactly the bug.

### Why regulation rather than policy wordings

Insurers do not publish a machine-readable archive of superseded wordings. A section of
regulation with a version history and an effective date is structurally the same object as a
policy wording with a version history and a loss date — and it is real. Inventing an archive
would have produced a number that measured the invention.

### Two things the data taught

**A version history is not a clean sequence of distinct dates.** Several sections carry two
entries with the **same** amendment date. A test case chosen without checking for that
failed spuriously, and the duplicate-date case is now asserted rather than worked around.

**A section number is not a key.** `1.1` is a real section in five of the six titles, and
140 identifiers appear in more than one. Merging the titles on the bare number would have
produced 3,029 sections instead of 3,204 — and the difference is not lost rows, it is **149
invented amendments**: one agency's rule change appearing in another agency's timeline.
Histories are keyed `title:identifier`, and there is a test that counts the invented
amendments so the shortcut cannot come back.

Reproduce it:

```bash
cd 15_claims-floor && python -m pytest tests/test_real_versions.py -q     # 13 passed
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
| `fnol-intake` | `claims`, `loss.date`, `loss.description` | a coverage decision |
| `coverage-checker` | `coverage` — from the version-pinned wording | reading a version that was not in force |
| `fraud-scorer` | `claims.signals` with the rule that fired | declining a claim |
| `adjuster-router` | `assignments` — solver output | reassigning to clear a queue |
| `settlement-writer` | `settlements.draft` | paying |
| `qa-sampler` | `qa_reviews` | overriding an adjuster |

## Architecture

| Topic | Carries |
|---|---|
| `claims.intake` | everything arriving from outside |
| `claims.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `claims.events` | the audit trail, and what the projector and SSE stream read |
| `claims.approvals` | an agent needs a person; resumes a checkpointed graph |
| `claims.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:claim:{id}` | two agents on one claim is how a duplicate payment happens |
| `cache:wording:{policy}:{version}` | the same wording is read by every agent on the claim |
| `idem:fnol:{reference}` | a claim reported by phone and by form is one claim |
| `live:sla` | ageing against the regulator's clock |

**Postgres:** `policies, policy_versions, claims, coverage, signals, assignments, settlements, events`.

**UI:** Nuxt 4 — a claim queue, a coverage view showing the clause and its version, a settlement composer.

## Real data

Synthetic claims against **real published policy wordings**, which insurers publish openly, with genuine version-effective dates. The wording versions are the part that has to be real; the claims do not.

## The deterministic core

`src/claimsfloor/domain.py` decides which policy version was in force on the loss date, and refuses to answer from any other. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 15_claims-floor
python -m pytest -q                      # 30 passed
PYTHONPATH="src;../platform/src" python -m claimsfloor.app    # console on http://127.0.0.1:8000
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

- **It does not decline a claim.** It reports coverage and the clause; a person declines.
- **It does not pay.** Settlement packs are drafts.
- **It does not score fraud with a model.** Rules that name themselves when they fire.
- **It does not read an unpinned wording.** A claim with no version in force is an error, not a default to the latest.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `issued_receipts`, `loss_date`, `peril`, `versions`

Published to `claims.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `coverage_reason`, `covered`, `draft`, `drop_rate`, `dropped_claims`, `issued_receipts`, `kept_claims`, `loss_date`, `model`, `no_version`, `paid`, `peril`, `settlement.draft`, `summary`, `summary_subject`, `version_id`, `versions` |

**The early exit**, on a payload that trips `cannot_assess`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
