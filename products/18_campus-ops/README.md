# 18 · campus-ops

> Education administration: admissions, timetabling, fee reconciliation, attendance and parent communications.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on 5,571 real scheduled events** across 3,440 days — Synthea's published
encounter data, which is a timetable in every respect that matters: a site, a person
delivering, a person receiving, and a span. Organisation is the room, provider is the
teacher, patient is the cohort.

| | |
|---|---:|
| Days with any clash | 45 of 3,440 (1.3%) |
| Distinct overlapping pairs | **46** |
| Clashes by dimension | room 37, teacher 37, cohort 36 |

The per-dimension counts are nearly identical, and the structure underneath them is the
result:

| Overlap trips | Pairs | What it is |
|---|---:|---|
| all three | 27 | a duplicate booking |
| room + teacher | 10 | one person, two clients, same place |
| **cohort only** | **9** | **the same person in two places at once** |

**A room-only checker catches 37 of 46 — and misses the nine that are physically
impossible.** Those nine are one individual booked at two different sites, with two
different staff, at overlapping times. Nothing about the rooms is wrong; both are free. The
contradiction is only visible on the third dimension.

That is the version of this product that shipped first: it checked rooms, because rooms are
the dimension people picture when they say "timetable clash". It would have published a
schedule containing every one of those nine.

**A double-booked teacher is exactly as common as a double-booked room** — 37 each. There is
no cheap dimension to skip.

### Why clinic data rather than a university timetable

The ITC-2007 timetabling instances are the obvious corpus and neither mirror served them
(both returned 404 pages). Rather than construct a timetable — which would have measured the
construction — the same three-dimensional question is asked of a real schedule that exists.
The mapping is exact and it is stated here so a reader can disagree with it.

Reproduce it:

```bash
cd 18_campus-ops && python -m pytest tests/test_real_schedule.py -q     # 10 passed
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
| `applicant-parser` | `applications.fields` with confidence | an admission decision |
| `eligibility-checker` | `eligibility` from published rules | an offer |
| `scheduler` | `timetables` — solver output only | publishing over a clash |
| `fee-reconciler` | `payments`, `matches` | waiving a fee |
| `parent-comms` | `messages.draft` | sending |
| `policy-answerer` | `answers` with the regulation cited, plus an abstain class | an answer from an unversioned policy |

## Architecture

| Topic | Carries |
|---|---|
| `campus.intake` | everything arriving from outside |
| `campus.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `campus.events` | the audit trail, and what the projector and SSE stream read |
| `campus.approvals` | an agent needs a person; resumes a checkpointed graph |
| `campus.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:timetable:{term}` | two schedulers publishing one term is a term of chaos |
| `cache:rules:{version}` | eligibility rules are read by every application |
| `idem:payment:{reference}` | bank files are re-imported |
| `live:attendance` | today's counters |

**Postgres:** `applicants, applications, cohorts, teachers, rooms, sessions, timetables, fees, payments, events`.

**UI:** HTMX + Jinja2 — an administrator's tool, server-rendered, works on the office machine that exists.

## Real data

Published university prospectuses and fee schedules, which are real and open, plus a generated cohort of the right size. The constraints have to be real; the students do not.

## The deterministic core

`src/campusops/domain.py` decides whether a timetable clashes with itself, in the three ways it can. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 18_campus-ops
python -m pytest -q                      # 30 passed
PYTHONPATH="src;../platform/src" python -m campusops.app    # console on http://127.0.0.1:8000
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

- **It does not admit or reject anyone.** Eligibility against published rules; a person decides.
- **It does not publish a timetable with a clash.** NotAuthorisedError, not warned about.
- **It does not waive or refund a fee.**
- **It does not answer a policy question from an unversioned document.** It abstains, and abstention rate is a reported metric.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `issued_receipts`, `sessions`

Published to `campus.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `clashes`, `draft`, `drop_rate`, `dropped_claims`, `issued_receipts`, `kept_claims`, `message.draft`, `model`, `publishable`, `published`, `sessions`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `not_publishable`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
