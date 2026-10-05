# 09 · hermes-home

> Self-hosted personal agent: durable memory that is gated on contradiction, an MCP tool surface, self-authored skills.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on LoCoMo** — ten real long conversations, a median of **29 sessions and 646
turns** each, with 1,986 questions whose answers point at the specific turns that support
them.

| | |
|---|---:|
| Questions with resolvable evidence | 1,982 of 1,986 |
| **Median distance back to the earliest supporting turn** | **14 sessions** |
| Furthest | 31 sessions |

What a sliding-window memory could answer:

| Window | Questions it can answer |
|---|---:|
| Last 1 session | 2.4% |
| Last 3 sessions | 12.0% |
| Last 8 sessions | **28.4%** |

**A sliding window cannot answer these questions, and making it bigger barely helps.**
Keeping the last eight of a median twenty-nine sessions still loses seventy-two per cent of
them. Eight times the window does not buy eight times the coverage; it buys a longer prompt.

This is the measured form of what `langchain-lab` project 03 found on a small scale: the
standard summary-plus-window memory scored identically to a free sliding window while
charging five model calls, and the naive summariser kept 100% of soft preferences and 0% of
hard constraints. A window keeps what is *recent*. What is needed is *old*.

Which is the argument for this product's shape: durable semantic memory, written only after
a contradiction check, rather than a longer context window.

**The earliest evidence binds, not the latest.** A question supported by sessions 3 and 27
is unanswerable without session 3, so the horizon is measured from the oldest turn a
question needs. Measuring from the newest would have made every one of these numbers look
far better and would have been meaningless.

Reproduce it:

```bash
cd 09_hermes-home && python -m pytest tests/test_real_memory.py -q     # 9 passed
```

### Still owed

The handoff constraint-survival measurement — hard-constraint survival at 50 turns, gated
against ungated — is implemented in `domain.py` and tested there, but has not been run
against a corpus with labelled hard constraints, because LoCoMo does not carry them. That
number is not claimed anywhere in this repository.

## Agents and write authority

`agentplatform.authority` is default-deny, so a field nobody was granted is closed and a
column added next month does not quietly become writable. **The table is declared here and
the pipeline does not yet consult it**: no node passes an agent identity, so this is a
statement of who *should* write what, checked for coherence by a test, not a runtime
guard. It said "enforced" until an independent review grepped for a caller and found two,
both inside `authority.py` itself.

| Agent | May write | Never |
|---|---|---|
| `conversation` | `messages`, `ctx:` | semantic memory |
| `memory-proposer` | `memory_candidates` | `memories` |
| `contradiction-checker` | `memories` — the only writer | a hard constraint, which a person settles |
| `skill-author` | `skills.draft` | `skills.active` |
| `tool-broker` | `tool_calls` | a call outside the allow-list |

## Architecture

| Topic | Carries |
|---|---|
| `home.intake` | everything arriving from outside |
| `home.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `home.events` | the audit trail, and what the projector and SSE stream read |
| `home.approvals` | an agent needs a person; resumes a checkpointed graph |
| `home.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `ctx:{conversation}` | working memory on the reply path |
| `lock:conversation:{id}` | two surfaces, one conversation |
| `llmcache:{sha}` | the same question from two surfaces |
| `ratelimit:{surface}` | web, Telegram and CLI have different budgets |

**Postgres:** `conversations, messages, memory_candidates, memories (with supersedes / contradicted_by edges), skills, tool_calls, events` — plus pgvector.

**UI:** Tauri desktop, plus a Telegram surface.

## Real data

Your own use, measured against **LongMemEval** and **LoCoMo** — public long-term-memory benchmarks with ground truth, so the memory claim is a number rather than a feeling.

## The deterministic core

`src/hermes/domain.py` decides which constraints must travel with a handoff, and refuses the handoff when a hard one would be dropped. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 09_hermes-home
python -m pytest -q                      # 24 passed
PYTHONPATH="src;../platform/src" python -m hermes.app    # console on http://127.0.0.1:8000
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

- **It does not write semantic memory from the reply path.** Memory writes run off `home.events`, so they never add latency to an answer.
- **It does not activate a skill it wrote.** Drafts only.
- **It does not call a tool outside the allow-list**, whatever the conversation says.
- **It does not resolve a hard-constraint contradiction.** It asks.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `constraints`, `issued_receipts`, `message`, `specialist`

Published to `home.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `carried`, `claims`, `constraints`, `draft`, `drop_rate`, `dropped_claims`, `hard_dropped`, `issued_receipts`, `kept_claims`, `memory_written`, `message`, `model`, `reply`, `soft_lost`, `specialist`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `handoff_refused`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
