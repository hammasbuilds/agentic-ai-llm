# 06 · oncall-mate

> An alert storm collapsed into one incident with a suspect, a runbook and a status update.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured on 32,000 real production log lines** — all sixteen of Loghub's published
samples, 2,000 lines each, one templater, no tuning per system.

| System | Distinct messages | Templates | Ratio | Messages seen once that stop existing |
|---|---:|---:|---:|---:|
| HDFS | 2,000 | 16 | **125.00x** | 1,997 |
| Apache | 1,461 | 12 | 121.75x | 1,157 |
| OpenStack | 2,000 | 50 | 40.00x | 1,995 |
| HealthApp | 2,000 | 75 | 26.67x | 1,969 |
| Linux | 2,000 | 178 | 11.24x | 1,903 |
| HPC | 1,999 | 180 | 11.11x | 1,886 |
| OpenSSH | 2,000 | 200 | 10.00x | 1,882 |
| Android | 1,988 | 227 | 8.76x | 1,874 |
| ZooKeeper | 1,999 | 244 | 8.19x | 1,781 |
| Hadoop | 1,985 | 277 | 7.17x | 1,740 |
| Spark | 1,862 | 390 | 4.77x | 1,483 |
| Proxifier | 1,704 | 572 | 2.98x | 1,184 |
| Mac | 1,991 | 706 | 2.82x | 1,543 |
| Thunderbird | 1,963 | 816 | 2.41x | 1,281 |
| Windows | 1,281 | 952 | 1.35x | 598 |
| BGL | 2,000 | 1,840 | **1.09x** | 185 |
| **All sixteen** | 30,233 | 6,735 | 4.49x | 24,458 |

**The compression ratio spans 115x across systems with the templater held constant.** It is
a property of the log, not of the templater — so a threshold tuned on one system says
nothing about the next. Pick "collapse to roughly 200 templates" and you get 16 on HDFS
(the incident is now invisible) and 1,840 on BGL (nothing was collapsed and the context
problem is exactly where it started).

**The last column is the one that matters.** An incident is made of the line that appeared
once. On HDFS, 2,000 messages are seen exactly once and only 3 templates are — 1,997
singletons stop existing as anything a correlator could point at. `log-detective` found
this on one corpus; across sixteen it is worse and it is not uniform.

Note what the bottom row does: pooled over all sixteen the ratio is 4.49x, which looks
unremarkable and sits *below the median of the systems it is made of*. **The per-system
table is the result; the headline number is the thing that hides it.**

### What tripling the systems changed, and what it did not

This was first measured on five systems. Extending to all sixteen is the check a
spread-shaped claim needs, and it came back split.

**The ends did not move at all.** BlueGene/L is still the floor and HDFS still the ceiling;
not one of the eleven newcomers reaches either, and the spread is still 115x. That is worth
recording because it is not the usual outcome — [fleet-desk](../17_fleet-desk)'s
single-instance spread understated itself badly.

**The middle was wrong.** Three of the original five compressed above 10x; only seven of
sixteen do. **The median ratio falls from 11.1 to 8.5**, so "expect roughly an order of
magnitude" was optimistic. Most production logs are considerably less repetitive than HDFS,
and Apache turning out to be the *second* most compressible system — 1,461 distinct lines
into 12 templates — is the kind of thing five samples cannot tell you.

Reproduce it:

```bash
cd 06_oncall-mate && python -m pytest tests/test_real_logs.py -q     # 19 passed
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
| `correlator` | `incidents`, `alert_links` — deterministic | a hypothesis |
| `hypothesiser` | `hypotheses`, each with linked evidence ids | an unevidenced hypothesis |
| `change-attributor` | `suspect_changes`, ranked by diff statistics | a suspect with no deploy record |
| `runbook-selector` | `proposed_actions` | executing anything |
| `comms-writer` | `status_drafts` | publishing |
| `pir-writer` | `reviews.draft` | a cause absent from the timeline |

## Architecture

| Topic | Carries |
|---|---|
| `ops.intake` | everything arriving from outside |
| `ops.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `ops.events` | the audit trail, and what the projector and SSE stream read |
| `ops.approvals` | an agent needs a person; resumes a checkpointed graph |
| `ops.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `dedupe:{fingerprint}` | the same alert fires every 30s until resolved |
| `lock:incident:{id}` | one correlator per incident |
| `live:board` | the wall display reads counters, not queries |
| `cache:promql:{sha}` | the same range query repeats across hypotheses |

**Postgres:** `alerts, incidents, hypotheses, evidence, changes, actions, reviews, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): A dense realtime board, built to live on a wall screen and survive a browser restart.

## Real data

**Loghub** — HDFS, BGL and Thunderbird, real public log datasets with labelled anomalies. `log-detective` already ran on 1,005 real captured log lines; this is the scale-up, and it resolves the 'needs real alerts' blocker that held this project up.

## The deterministic core

`src/oncall/domain.py` decides which alerts belong to one incident, and refuses to chain unrelated services into a single storm. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 06_oncall-mate
python -m pytest -q                      # 37 passed
PYTHONPATH="src;../platform/src" python -m oncall.app    # console on http://127.0.0.1:8000
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

- **It does not execute a remediation.** It proposes; a person runs it.
- **It does not show a hypothesis without its evidence.** No evidence link, no row.
- **It does not page on its own** unless a rule a human wrote says to.
- **It does not rank blast radius by opinion.** Diff statistics, reusing `release-captain`'s work.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `alerts`, `claims`, `issued_receipts`

Published to `ops.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `action.proposed`, `alerts`, `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `draft`, `drop_rate`, `dropped_claims`, `executed`, `incidents`, `issued_receipts`, `kept_claims`, `model`, `receipts_source`, `reduction`, `summary`, `summary_subject` |

**The early exit**, on a payload that trips `no_incident`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
