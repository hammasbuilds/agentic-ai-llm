# 07 · hire-desk

> CV parsing, blind scoring against a fixed rubric, an interview kit, and a fairness audit that runs continuously.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Redacting a name does not redact a person.**

Measured on ten long real conversations — 5,882 turns between named people, talking the way
people do.

| | |
|---|---:|
| Exact name occurrences removed | **1,971** |
| Conversations where the person is still plainly identifiable | **3 of 10 (30%)** |

What survived:

| Redacted | Survived as | Times |
|---|---|---:|
| Melanie | **Mel** | **59** |
| Deborah | Deb | 41 |
| Calvin | Cal | 25 |
| Caroline | Caro | 2 |
| Melanie | Mell | 1 |
| Deborah | Debs | 1 |

`Mel` appears fifty-nine times *after* every occurrence of `Melanie` was removed. A reviewer
reading the blinded document does not need the full name, and blind scoring is not blind.

That is why this product's leak check is not decoration. The barrier is a topic boundary —
the scorer consumes a different topic and is structurally unable to receive the identified
record — and the leak check is what proves the thing crossing that boundary is actually
anonymous.

### The detector matters as much as the number

A strict detector, counting a short form only when it follows a greeting, finds **1 of 10**.
The broader one finds 3. The broader one is not looser about evidence: it separates a name
from an ordinary word by whether the word ever appears lower case in the same text.
`Nature` shares three characters with `Nate` and appears as `nature` constantly; `Mel` never
does. No dictionary, no hand-listed diminutives.

Both numbers are in the tests, because a leak rate without its detector is not a
measurement.

### Why conversation rather than CVs

No real CV corpus is available, and inventing one would break the no-fabricated-dataset
rule. Real conversation has the property that matters
— names used naturally, including the short forms nobody thinks to redact. **The
identified-versus-redacted score delta is therefore still unmeasured**, and is not claimed.

Reproduce it:

```bash
cd 07_hire-desk && python -m pytest tests/test_real_redaction.py -q     # 9 passed
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
| `cv-parser` | `candidates.fields` with confidence | a score |
| `redactor` | `redacted_views` — deterministic | anything else |
| `scorer` | `scores` per rubric dimension, from the redacted view only | a free-text overall verdict |
| `kit-builder` | `interview_kits` | a question outside the rubric |
| `scheduler` | `slots` | booking without approval |
| `fairness-auditor` | `audit_reports` | suppressing a measure |

## Architecture

| Topic | Carries |
|---|---|
| `hire.intake` | everything arriving from outside |
| `hire.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `hire.events` | the audit trail, and what the projector and SSE stream read |
| `hire.approvals` | an agent needs a person; resumes a checkpointed graph |
| `hire.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:cv:{sha256}` | the same CV arrives via three job boards |
| `lock:candidate:{id}` | one scoring run per candidate |
| `budget:{role}:{day}` | bulk intake must not eat a day's tokens |
| `cache:parse:{sha256}` | re-parsing a CV is pure waste |

**Postgres:** `roles, candidates, redacted_views, scores, kits, interviews, audits, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Ember Octane, or FastAPI + Jinja + Tailwind if Ember is not worth the learning cost — a role board, a blind-scoring queue, and a standing fairness page.

## Real data

A local file of mined hiring posts (`extracted.jsonl`, not published) for the roles, a public résumé corpus for the candidates, and **name-swapped duplicates** for the fairness audit — the same CV under several names is the only honest way to measure this. ⚠️ This product does not start until a real CV corpus is sourced; inventing CVs breaks the no-fabricated-dataset rule.

## The deterministic core

`src/hiredesk/domain.py` decides what the scorer is allowed to see, and whether anything identifying survived redaction. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 07_hire-desk
python -m pytest -q                      # 27 passed
PYTHONPATH="src;../platform/src" python -m hiredesk.app    # console on http://127.0.0.1:8000
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

- **It does not reject a candidate.** It scores against a published rubric and ranks.
- **It does not let the scorer see an identified record.** The scoring worker consumes a different topic; it is structurally unable to.
- **It does not produce an overall verdict from a model.** Dimensions are structured-decoded and summed in Python.
- **It does not report one fairness measure.** All four incompatible ones, the `credit-risk-engine` pattern.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `cv`, `issued_receipts`, `secrets`

Published to `hire.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `cv`, `decision`, `draft`, `drop_rate`, `dropped_claims`, `interview_kit`, `issued_receipts`, `kept_claims`, `leaks`, `model`, `redacted_view`, `removed`, `secrets`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `refused_to_score`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
