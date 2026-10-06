# 13 · swarm-lab

> A scaling observatory: what actually happens to a multi-agent system as N grows.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured by running N real threads over a shared entity list**, 40 entities, three
repeats per cell. No model is involved, deliberately: duplicate calls and conflicting
writes are structural — they come from workers sharing a queue and a store, not from what
any of them is thinking — so removing the model removes the largest source of variance
from a study whose subject is N.

The lock is a real `SET NX` against Redis when one answers and `InMemoryCache.add`
otherwise, and `sweep.backend()` says which. **The tables below were produced by the
in-memory path — no Redis was up on this machine** — and they are byte-identical to the
Redis path, because what is being counted is how often two threads reach for the same
entity and neither cache changes that. This line used to read "against the real Redis"
without qualification, which was a claim about infrastructure that a silent fallback had
already made false.

### Uncoordinated, flat

| N | Tool calls | Duplicates | Wasted | Conflicting writes |
|---:|---:|---:|---:|---:|
| 1 | 40 | 0 | 0% | 0 |
| 2 | 80 | 40 | 50.0% | 40 |
| 3 | 120 | 80 | 66.7% | 40 |
| 5 | 200 | 160 | 80.0% | 40 |
| 8 | 320 | 280 | 87.5% | 40 |
| 13 | 520 | 480 | 92.3% | 40 |
| 21 | 840 | 800 | **95.2%** | 40 |

**Wasted work is exactly `1 - 1/N`.** Not approximately: exactly, at every N, because
without coordination every agent does every piece of work. At twenty-one agents, 95% of
everything the swarm does is a repeat of something another agent is already doing.

**Conflicting writes saturate at two agents.** Every entity collects a conflicting write the
moment there is more than one worker; going from 2 to 21 does not add conflicts, it makes
each one deeper. The headline "more agents, more conflicts" is wrong — the damage is done at
N=2 and the rest is depth.

### With a Redis lock

| N | Tool calls | Duplicates | Conflicts | Lock contentions |
|---:|---:|---:|---:|---:|
| 2 | 40 | 0 | 0 | 40 |
| 5 | 40 | 0 | 0 | 160 |
| 13 | 40 | 0 | 0 | 480 |
| 21 | 40 | 0 | 0 | 800 |

Work is done exactly once at every N. The cost moves entirely into contention, which grows
as `entities x (N-1)` — **linear in N, while the duplicated work it prevents grows with N
times the work itself.** That asymmetry is why the lock is worth its latency.

A supervisor that partitions the list achieves the same with no lock at all: topology
substitutes for coordination. Both are in the tests.

`InMemoryCache.add` is the lock on that path, and it was a membership test followed by an
assignment — two operations with a thread switch possible between them, which would hand
two agents the same lock and quietly turn the 0 duplicates above into an undercount. It
could not be made to double-grant on this interpreter in 400 trials of eight contending
threads with the switch interval at a nanosecond, so it was correct by a property of the
GIL rather than by construction. It is guarded now, and that trial is a test.

### Scope

These are agents with no shared state, which is the upper bound on waste rather than a
typical system — real agents coordinate partially. The `1 - 1/N` law and the lock result are
exact for that bound, and the shape is what a scaling study is for: it says where to spend
effort, and it says the answer is coordination rather than parallelism.

Reproduce it:

```bash
cd 13_swarm-lab && python -m pytest tests/test_real_sweep.py -q     # 12 passed
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
| `sweep-runner` | `trial.*` | interpreting a result |
| `collector` | `metric.*` | a metric it did not count |
| `narrator` | `report.draft` | a number absent from `metrics` |

`worker` appeared in this table with no grant anywhere in `swarmlab/agents.py`. Default-deny means they may write nothing, so the rows claiming otherwise are gone: an intended agent is not a declared one, and this column is generated from the code rather than written beside it.

## Architecture

| Topic | Carries |
|---|---|
| `swarm.intake` | everything arriving from outside |
| `swarm.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `swarm.events` | the audit trail, and what the projector and SSE stream read |
| `swarm.approvals` | an agent needs a person; resumes a checkpointed graph |
| `swarm.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:entity:{id}` | the contention this study exists to measure |
| `budget:{trial}` | a runaway sweep must not eat a day |
| `live:sweep` | progress for the page |
| `idem:trial:{n}:{repeat}` | a resumed sweep must not double-count |

**Postgres:** `sweeps, trials, tool_calls, writes, metrics, reports, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Observable Framework — one page per sweep, with the curve as the artefact.

## Real data

The infrastructure already exists: `mcp-lab`, `bounded-agent-runtime`, `enterprise-ops-crew`, `langgraph-lab`. Zero downloads. The failure mode has already happened here for real — a broad `taskkill` killed sibling agents' live runs — which is why `powerguard`'s ownership rule and this study's conflict metric are the same idea.

## The deterministic core

`src/swarmlab/domain.py` decides duplicate tool calls and conflicting writes — the two metrics that only exist because there is a bus and a shared store. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 13_swarm-lab
python -m pytest -q                      # 32 passed
PYTHONPATH="src;../platform/src" python -m swarmlab.app    # console on http://127.0.0.1:8000
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

- **It does not claim a framework is better.** The model and the task are held constant; N is the variable.
- **It does not report a single run.** At least three repeats per cell, and the spread is reported.
- **It does not estimate a token count.** Counted from the trace.
- **It does not build a swarm as a product.** Building it is not the valuable part; measuring it is.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `calls`, `claims`, `issued_receipts`, `repeats`, `writes`

Published to `swarm.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `branch_status`, `branches`, `branches_failed`, `calls`, `claims`, `claims_checked`, `claims_source`, `conflicts`, `draft`, `drop_rate`, `dropped_claims`, `duplicate_calls`, `issued_receipts`, `kept_claims`, `model`, `published`, `receipts_source`, `repeats`, `report.draft`, `reportable`, `summary`, `summary_subject`, `writes` |

**The early exit**, on a payload that trips `not_reportable`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
