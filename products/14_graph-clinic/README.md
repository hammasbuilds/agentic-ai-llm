# 14 · graph-clinic

> Clinical evidence assistant over a knowledge graph, where every answer carries the path it came from.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on all 7,405 HotpotQA validation questions**, read from the local HuggingFace
cache. Each has two gold paragraphs hidden among ten, and each is labelled `bridge` (hop
from one paragraph to another) or `comparison` (read two and compare).

The graph is built from real title mentions: a paragraph titled "Scott Derrickson" that
names "Ed Wood" in its text is an edge between two entities.

| Question type | n | Graph, 1 hop | Graph, 2 hops | Lexical top-2 |
|---|---:|---:|---:|---:|
| **bridge** | 5,918 | **75.3%** | 76.6% | 16.7% |
| **comparison** | 1,487 | **0.1%** | 1.3% | 8.7% |
| All | 7,405 | 60.2% | 61.5% | 15.1% |

**The graph does not beat the baseline or lose to it. It answers a different question.**

On bridge questions it is four and a half times the baseline, because a bridge question *is*
a hop and a mention edge *is* that hop. On comparison questions one hop finds the pair in
one case in a thousand — not weaker than the baseline, absent — because "were these two
directors the same nationality" needs two unrelated pages and there is no edge between them.
The question is not about a relationship.

The bottom row is the trap. 60% against 15% reads as *the graph wins, use it everywhere*,
and that would be the wrong call for a fifth of the traffic. **The routing decision, not the
retriever, is the product.**

Two smaller results worth keeping:

- **The second hop buys almost nothing** — 75.3% to 76.6%. Nearly all the value is in the
  direct mention, which argues for a hop cap of one and against the unbounded walks this
  category usually ships.
- **The median item has two mention edges** among ten paragraphs (mean 4.1). The graph is
  sparse, which is why traversal is cheap when it works at all.

### The 3,000-question sample was fine here, and that is worth explaining

These numbers were first measured on 3,000 questions: bridge 73.4%, overall 60.0%. On all
7,405 they are 75.3% and 60.2%. Two points and two tenths of a point.

That is the opposite of what happened in [comms-desk](../05_comms-desk), where going from a
twelve-meeting sample to the full corpus moved the headline from 62% to 87%. The difference
is structural, not luck. **This measurement is a per-item rate** — each question is scored
independently, so a sample estimates it honestly. **comms-desk's was a collision count over
the whole pool** — wrong merges are pairs of different speakers, and a sample shrinks the
pool that pairs are drawn from, so it can only undercount. Sampling is safe for the first
kind and structurally misleading for the second, and knowing which one you have is the
difference between a shortcut and a wrong answer.

### This contradicts what this README used to predict

The stated prior was that graph traversal would lose, on the strength of `rag-lab`'s result
that six of eight clever retrieval variants lost to a plain hybrid baseline. On bridge
questions it wins decisively. The prior was wrong for half the corpus and right for the
other half, and the useful output is the split rather than either verdict.

Reproduce it:

```bash
cd 14_graph-clinic && python -m pytest tests/test_real_graph.py -q     # 12 passed
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
| `ingester` | `document.*` | an entity or a relation |
| `entity-linker` | `mention.*` | a relation |
| `graph-builder` | `edge.*` | an inferred edge |
| `synthesiser` | `answer.draft` | an answer whose path is empty |

`contradiction-reporter`, `traversal-planner` appeared in this table with no grant anywhere in `graphclinic/agents.py`. Default-deny means they may write nothing, so the rows claiming otherwise are gone: an intended agent is not a declared one, and this column is generated from the code rather than written beside it.

## Architecture

| Topic | Carries |
|---|---|
| `graph.intake` | everything arriving from outside |
| `graph.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `graph.events` | the audit trail, and what the projector and SSE stream read |
| `graph.approvals` | an agent needs a person; resumes a checkpointed graph |
| `graph.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `cache:path:{start}:{hops}` | traversals repeat across questions |
| `lock:ingest:{doc}` | one builder per document |
| `idem:doc:{sha256}` | corpora ship duplicates |
| `live:graph` | node and edge counters |

**Postgres:** Postgres for documents and answers; **Neo4j** for the graph itself. `documents, mentions, queries, answers, contradictions, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): React + Cytoscape.js — the graph is the interface, not a decoration beside it.

## Real data

`Morson/mimic_ex` — 220 MB, **not** gated, the workable substitute for MIMIC-IV. ⚠️ The paper's middle tier (MedC-K / S2ORC) is a dead end: the authors cannot release raw content. Say that in the README. UMLS is free but needs an application — submit it early. ⚠️ The 'ACL 2025' claim on the source repo returned nothing from Semantic Scholar; verify before citing.

## The deterministic core

`src/graphclinic/domain.py` decides a bounded, cycle-safe walk that carries the source of every edge it crossed. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 14_graph-clinic
python -m pytest -q                      # 17 passed, 12 skipped
PYTHONPATH="src;../platform/src" python -m graphclinic.app    # console on http://127.0.0.1:8000
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

- **It does not diagnose or advise on treatment.** It retrieves and cites.
- **It does not infer an edge.** An edge exists because a document stated it, and the edge names the document.
- **It does not walk unbounded.** Hop limits are arguments, not conventions.
- **It does not reproduce the paper.** Two of three data tiers are reachable; the middle one is not, and the README says so.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `claims`, `edges`, `end`, `issued_receipts`, `start`

Published to `graph.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `answer.draft`, `branch_status`, `branches`, `branches_failed`, `cites`, `claims`, `claims_checked`, `claims_source`, `draft`, `drop_rate`, `dropped_claims`, `edges`, `end`, `issued_receipts`, `kept_claims`, `model`, `path`, `path_sources`, `reachable`, `receipts_source`, `start`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `no_path`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
