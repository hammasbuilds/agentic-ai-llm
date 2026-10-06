# 05 · comms-desk

> Email and meetings reconciled into one board of commitments, each attributed to who made it.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on the whole AMI Meeting Corpus** — all 139 real recorded meetings, 104,923
hand-annotated dialogue acts across 556 speaker slots, of which **10,462 are Suggest or
Offer**: the acts that put someone on the hook.

| Similarity threshold | Duplicates found | Speaker-blind | **Wrong merges** |
|---:|---:|---:|---:|
| 0.5 | 100 | 786 | **686 — 87% of everything it merged** |
| 0.6 | 45 | 245 | 200 — 82% |
| 0.7 | 24 | 89 | 65 — 73% |

**At the threshold you need to catch genuine restatements, ignoring who spoke makes 786
merges of which 686 join two different people's commitments.** Seven out of every eight
merges are wrong, and each wrong merge deletes someone's promise from the board.

Tightening the threshold does not rescue it. At 0.7 the merging has nearly stopped being
useful — 24 genuine duplicates in ten thousand commitments — and going speaker-blind still
gets 73% of its merges wrong. There is no threshold that separates the two, which is why
**speaker is a hard barrier here and never a weighted feature in a similarity score.**
There is a test asserting no threshold, however loose, merges across speakers.

### The sample was not just imprecise, it was low

This was first measured on twelve meetings, which put the wrong-merge share at **62%**. The
full corpus says **87%**. That gap is not sampling luck, and the direction was predictable:
wrong merges are cross-speaker collisions, so they grow with the number of speakers in the
pool. Twelve meetings held 48 speaker slots; 139 hold 556. **Any sample of this measurement
is a floor, never an estimate** — which is the argument for paying the runtime.

Measuring it all needed the merge step to stop being quadratic. `dedupe` now blocks
candidates on `(speaker, token)` and memoises tokenisation, which took the corpus-wide run
from over ten minutes to about twenty seconds *and returns the identical clusters* — there
is a test that runs the old pairwise version beside it on real data and compares cluster
membership, because an optimisation that silently drops a real duplicate is precisely the
bug this product exists to catch.

### What this corpus cannot show, said plainly

The within-meeting duplicate rate is about **1%** (100 in 10,462) — people rarely restate a commitment
inside one conversation. The duplication this product is built for is **cross-source**: the
same promise made in a meeting and repeated in a follow-up email. AMI is meetings only, so
that rate is not measurable here and is not claimed. What AMI does establish is the thing
that matters more: the merge step is where this class of product breaks, and the speaker
barrier is what stops it.

Reproduce it:

```bash
cd 05_comms-desk && python -m pytest tests/test_real_meetings.py -q     # 10 passed, ~80s
```

It takes eighty seconds because it reads all 139 meetings and runs the speaker-blind
baseline three times. That baseline is the expensive half — dropping the speaker drops the
only barrier that partitions the work.

## Agents and write authority

`agentplatform.authority` is default-deny, so a field nobody was granted is closed and a
column added next month does not quietly become writable. **The table is declared here and
the pipeline does not yet consult it**: no node passes an agent identity, so this is a
statement of who *should* write what, checked for coherence by a test, not a runtime
guard. It said "enforced" until an independent review grepped for a caller and found two,
both inside `authority.py` itself.

| Agent | May write | Never |
|---|---|---|
| `triage` | `thread.category` | archiving or deleting |
| `extractor` | `commitment.*` | a commitment with no source span |
| `reply-writer` | `draft.*` | sending — no exception |
| `scheduler` | `slot.proposed` | booking without approval |

`reconciler`, `transcriber` appeared in this table with no grant anywhere in `comms/agents.py`. Default-deny means they may write nothing, so the rows claiming otherwise are gone: an intended agent is not a declared one, and this column is generated from the code rather than written beside it.

## Architecture

| Topic | Carries |
|---|---|
| `comms.intake` | everything arriving from outside |
| `comms.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `comms.events` | the audit trail, and what the projector and SSE stream read |
| `comms.approvals` | an agent needs a person; resumes a checkpointed graph |
| `comms.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `idem:{mailbox}:{rfc822_id}` | IMAP redelivers on reconnect |
| `lock:thread:{id}` | one triage run per thread |
| `ctx:{thread}` | working memory across a thread's turns |
| `cache:freebusy:{calendar}` | CalDAV is slow and repeats |

**Postgres:** `threads, messages, meetings, transcripts, commitments, drafts, slots, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Svelte 5 (runes) — triage queue, transcript with speaker lanes, and a single commitments board fed by both sources.

## Real data

The **Enron corpus** (~500k real emails) for triage, and the **AMI Meeting Corpus** — real recordings with reference transcripts and annotations — for extraction. Both openly available.

## The deterministic core

`src/comms/domain.py` decides which commitments are the same commitment, and which merges must never happen. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 05_comms-desk
python -m pytest -q                      # 24 passed, ~86s
PYTHONPATH="src;../platform/src" python -m comms.app    # console on http://127.0.0.1:8000
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

- **It does not send.** Not once, not with a confirmation dialogue.
- **It does not archive or delete mail.** Categories only.
- **It does not keep a commitment it cannot attribute.** No speaker and timestamp, no row.
- **It does not merge across speakers.** Two people promising similar things are two commitments.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `commitments`, `issued_receipts`

Published to `comms.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `clusters`, `commitments`, `draft`, `drop_rate`, `dropped_claims`, `duplicates`, `issued_receipts`, `kept_claims`, `model`, `receipts_source`, `sent`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `nothing_to_do`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
