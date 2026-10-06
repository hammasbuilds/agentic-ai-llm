# 03 · one-desk

> Portfolio, LinkedIn, Instagram and X in one calendar, one inbox and one approval tray.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

The claim under test is that per-platform "voice adaptation" produces four genuinely
different texts. Testing it needs two things: a yardstick for how different real renderings
of one thing are, and **output from a real adapter**.

**The yardstick.** Each AMI meeting carries up to four participant summaries — the same
hour, written up separately by each person who was in the room, with no instruction to
differ. 300 summaries, 80 meetings, 397 same-meeting pairs.

**The adapter.** 12 real source texts through a local `qwen2.5:14b-instruct`, asked
for a LinkedIn post, an Instagram caption, an X post and a portfolio note: 48 generations,
cached in `data/adapter_runs.json` by `scripts/run_adapter.py`.

| | Median content-word overlap |
|---|---:|
| Adapter variant vs **its source** | **0.528** |
| Adapter variant vs **another variant** | **0.290** |
| Two people, same meeting | **0.229** |
| Two people, different meetings | 0.156 |

### The human baseline is seven points wide, and it had to be tested

The bottom two rows are the yardstick, and the gap between them is the whole signal: two
people describing **one** meeting overlap at 0.229; two people describing **different**
meetings overlap at 0.156, purely from the vocabulary of describing a meeting at all.

**0.073 is small enough that reporting it untested would be a guess.** It survives:

| | |
|---|---:|
| Separation | **0.073** |
| Permutation test, 10,000 label shuffles | **0 reach it** (p < 0.0001) |
| 95% bootstrap interval | **[0.060, 0.085]** |

Small *and* real is exactly the useful outcome. If the gap were large, two people describing
one meeting would substantially agree, and nothing a rewriter produced would look
impressive by comparison. It is 0.073 — which is what makes the numbers above mean
something.

The control also used to stop at the first 40 meetings, for no reason the code gave. All 80
cost 3,160 comparisons, which is nothing; it moved the control median from 0.159 to 0.156.
A `limit=400` parameter on `baseline()` was dead — never read in the body — and is gone.

### The adaptation is real, and this README predicted the opposite

**Four variants of one source differ from each other about as much as two independent
people rendering the same content differ** — 0.290 against a human baseline of 0.229. They
are not four copies with different hashtags.

The earlier version of this section predicted near-identical variants and concluded "stop
paying for four generations". That prediction was made against a hand-written example pair
rather than a real run, and the real run does not support it. The conclusion is withdrawn.

### What the adapter does cost

Each variant keeps **half its source's content words**, where an independent rendering of
the same content keeps under a quarter. **The adapter paraphrases where a person
re-conceives** — 2.3x closer to the source than a human writing from the same material.

Whether that is a fault depends on what you want. For a social surface it is arguably
correct: the post should still be about the thing. It is worth knowing, and it is the honest
version of "the model is not really rewriting".

### Where the generations could actually be saved

How much a platform transforms varies twofold, and it tracks the prompt:

| Platform | Overlap with source |
|---|---:|
| Instagram | 0.333 |
| LinkedIn | 0.426 |
| Portfolio | 0.609 |
| **X** | **0.682** |

**X and the portfolio note barely leave the source.** Those two are the candidates for a
deterministic template — truncate, adjust register, done — which would halve the generation
budget without losing anything a measurement can detect. Instagram and LinkedIn are doing
real work.

### Still not measured

Engagement by posting time. That needs the account owner's own history, and no substitute
exists. `domain.best_hour` computes it from real history; there is no real history here, so
no engagement figure is claimed anywhere in this repository.

Reproduce it:

```bash
python scripts/run_adapter.py 12     # ~4 min on this card, writes the cache
cd 03_one-desk && python -m pytest -q     # 35 passed
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
| `planner` | `calendar` slots | published content |
| `adapter` | `post_variants` | `posts.published` |
| `brand-guard` | a veto, with a reason | anything else |
| `comment-triage` | `threads.intent`, the escalation flag | a public reply |
| `reply-writer` | `reply_drafts` | auto-publishing, ever |
| `analyst` | `metrics_rollups` (computed) | a metric it did not fetch |

## Architecture

| Topic | Carries |
|---|---|
| `social.intake` | everything arriving from outside |
| `social.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `social.events` | the audit trail, and what the projector and SSE stream read |
| `social.approvals` | an agent needs a person; resumes a checkpointed graph |
| `social.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:slot:{platform}:{time}` | prevents the same slot publishing twice |
| `ratelimit:{platform}` | four APIs, four different limits |
| `idem:{platform}:{webhook_id}` | webhook deliveries repeat |
| `live:engagement` | dashboard counters without a query |

**Postgres:** `ideas, calendar, post_variants, posts, threads, reply_drafts, metrics, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Preact + Signals — four-column calendar, unified inbox, approval tray, one analytics page comparing platforms on the same axis.

## Real data

Your own accounts and your own post history. The one product here whose demo data is genuinely yours and genuinely real.

## The deterministic core

`src/onedesk/domain.py` decides how much two platform variants actually differ, and when your own history says to post. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 03_one-desk
python -m pytest -q                      # 35 passed
PYTHONPATH="src;../platform/src" python -m onedesk.app    # console on http://127.0.0.1:8000
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

- **It does not auto-reply in public.** Drafts only, always.
- **It does not buy engagement, follow, or mass-DM.** Nothing here touches a growth-hacking pattern.
- **It does not claim a metric it did not fetch.** Every figure carries its fetch time.
- **It does not use a model to pick a posting time.** That is a count over your own history.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `baseline`, `claims`, `idea`, `issued_receipts`, `variants`

Published to `social.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `baseline`, `branch_status`, `branches`, `branches_failed`, `claims`, `draft`, `drop_rate`, `dropped_claims`, `idea`, `issued_receipts`, `kept_claims`, `max_overlap`, `model`, `overlaps`, `published`, `scheduled`, `summary`, `summary_subject`, `variants` |

**The early exit**, on a payload that trips `vetoed`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
