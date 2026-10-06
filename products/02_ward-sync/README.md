# 02 · ward-sync

> Hospital operations agents: intake, bed and theatre assignment, result routing, discharge, pre-authorisation.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on Synthea's published patient sample** — 3,850 medication records across 105
patients and 5,571 encounters, openly available and needing no credentialing.

| | |
|---|---:|
| Medication records | 3,850 |
| **Carrying a STOP date** | **3,582 (93.0%)** |
| Of those, a single administration (start and stop the same day) | 1,006 |
| Patients whose naive "current list" names a discontinued drug | **104 of 105 (99.0%)** |
| Median overstatement of that list | **5.54x** |

A "current medication list" assembled by asking what was *started*, and never what was
*stopped*, names five and a half times too many drugs — and it is wrong for essentially
every patient, not for an unlucky few.

That is not an exotic failure. It is what a summary agent is working from whenever it is
handed a medications table and reads the START column, which is the obvious thing to do and
the reason this product reads the event stream instead. **93% of prescriptions end.** A
model asked to summarise a stay will faithfully report a drug the patient stopped taking,
and it will read perfectly well.

The gate is the second half: a sentence in a discharge draft that cannot cite an event id
from this encounter is removed before a clinician sees it. A reviewer asked to spot a
stopped drug inside otherwise fluent prose will not spot it.

Reproduce it:

```bash
cd 02_ward-sync && python -m pytest tests/test_real_records.py -q     # 9 passed
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
| `intake` | `encounters`, `patient.demographics` | any clinical field |
| `triage-router` | `encounter.department`, `encounter.acuity_band` | a diagnosis |
| `bed-planner` | `assignments` — solver output only | an assignment that breaks a constraint |
| `results-router` | `notifications` | a result value |
| `discharge-writer` | `summaries.draft` | `summaries.final` — a clinician signs |
| `preauth-packer` | `claims.draft`, the attachment list | a justification not in the record |

## Architecture

| Topic | Carries |
|---|---|
| `ward.intake` | everything arriving from outside |
| `ward.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `ward.events` | the audit trail, and what the projector and SSE stream read |
| `ward.approvals` | an agent needs a person; resumes a checkpointed graph |
| `ward.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:bed:{id}` | double-booking a bed is the classic failure here |
| `live:occupancy` | the floor board reads this, not Postgres |
| `ctx:{encounter}` | working memory for one encounter's run |
| `idem:lab:{result_id}` | lab interfaces redeliver on reconnect |

**Postgres:** `patients, encounters, assignments, orders, results, summaries, claims, events` — `events` is the clinical audit log and the source of truth for state.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Refine + Ant Design — floor board, encounter timeline, clinician sign-off queue, pre-auth tray.

## Real data

**Synthea** — open source, generates complete synthetic patient histories in FHIR with no credentialing. Optionally MIMIC-IV-demo, 100 patients, openly available.

## The deterministic core

`src/ward/domain.py` decides which medications are actually active, and which drafted sentences have no event to stand on. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 02_ward-sync
python -m pytest -q                      # 25 passed
PYTHONPATH="src;../platform/src" python -m ward.app    # console on http://127.0.0.1:8000
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

- **It does not diagnose.** Not a clinical decision tool; an operations tool. That is both the ethical position and the commercially real one.
- **It does not sign anything.** Every clinical artefact stops at draft.
- **It does not assign a bed with a model.** Assignment is a constraint solver; the model explains the result.
- **It does not read a medication list.** It reads the event stream, which is the entire point.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `encounter`, `events`, `issued_receipts`

Published to `ward.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `active_medications`, `branch_status`, `branches`, `branches_failed`, `claims`, `draft`, `drop_rate`, `dropped_claims`, `encounter`, `events`, `issued_receipts`, `kept_claims`, `model`, `must_not_mention`, `signed`, `summary`, `summary.draft`, `summary_subject` |

**The early exit**, on a payload that trips `escalated`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
