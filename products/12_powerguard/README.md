# 12 · powerguard

> Machine custodian: on mains loss, checkpoint the training run, pause the downloads, sleep the displays, hibernate before the battery goes.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

Measured against a real Windows workstation's process table, not a fixture.

### 1 · On a shared machine, the custodian protects nothing — and that is correct

| | |
|---|---:|
| Processes running | 392 |
| Expensive jobs worth protecting | 3 |
| **Of those, started by another session** | **3** |
| Actions planned against them on simulated mains loss | **0** |

The three are `ollama app.exe`, `ollama.exe` and `llama-server.exe` — the model server
holding 9.2 GB of this card. They are precisely what an outage would destroy, and precisely
what this custodian must not signal. So the plan for a real power cut here is one action:
sleep the displays. It reports the rest and reaches for none of it.

That is the whole product. A custodian that signals a PID it did not start is worse than no
custodian.

**But "3 of 3" is a snapshot, and a snapshot is not a guarantee.** The table above describes
one machine at one moment. The guarantee is asserted separately over **4,000 generated
machine states** — both power states, the whole battery range, every mix of owned and
unowned work — and in none of them is an action ever aimed at a pid this custodian does not
own.

### 1b · The generated states found the hole in that guarantee

`plan` refuses to signal a process it does not own. Then, on a flat battery, it hibernates
the machine — **and hibernation reaches every process on it.** It carries no pid because it
is not aimed at a process, so no ownership check applies to it.

Hibernation is not a kill: Windows writes memory to disk and processes resume. But a CUDA
context does not reliably survive it and an open socket does not survive it at all, so
another session's training run or download is genuinely at risk from an action this
custodian took. The per-process guarantee was real and it was not the whole story.

The fix is not to refuse. Losing mains on a flat battery ends that work anyway, and
unhibernated it ends worse. The fix is to say so, so the hibernate action now reads:

```
hibernate system — battery 5%, 3 min left; SUSPENDS 1 job(s) belonging to
                   another session: ollama.exe(99)
```

A live test could never have found this: it needs a flat battery *and* another session's
job, and the test machine has not been on battery while that was true.

### 2 · A classifier that reads an install path is reading noise

The first version matched the raw command line and found **14** expensive jobs. Eleven were
ordinary Python processes, matched because the interpreter lives under
`...\AppData\Roaming\uv\python\...` and `\buv\b` matches inside a path.

Classifying on the executable's basename plus its arguments takes 14 down to **3**. A
custodian acting on the first number would have paused eleven unrelated processes during an
outage.

### 3 · A process name is not an identity — caught by this product's own test

The planner originally named its target: `checkpoint python.exe`. Run under pytest on this
machine, `jobs()` sees two `python.exe` processes — the test run itself, owned, and another
session's, not — and the plan produced an instruction that could not be carried out safely.
**`Action` now carries a `pid`, and refuses to be constructed without one** unless the
target is not a process at all.

This is the exact class of mistake the product exists to prevent, found by running it
against real state rather than by imagining it.

### Still owed

Work lost per outage, before and after, is the number this README set out to produce. It
needs outages, and the honest position is that none have been observed while the custodian
was watching. The baseline is on record — five dead model pulls and a training run paused at
epoch 18 — but it was gathered before this existed and is not a measurement this product
made.

Reproduce it:

```bash
cd 12_powerguard && python -m pytest tests/test_real_machine.py -q     # 28 passed
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
| `sensor-watcher` | `reading.*` | any action |
| `policy-engine` | `plan.*` | executing a plan |
| `job-custodian` | `action.*` | any PID it does not own |
| `incident-narrator` | `event.summary` | a figure it did not read |

`resume-planner` appeared in this table with no grant anywhere in `powerguard/agents.py`. Default-deny means they may write nothing, so the rows claiming otherwise are gone: an intended agent is not a declared one, and this column is generated from the code rather than written beside it.

## Architecture

| Topic | Carries |
|---|---|
| `power.intake` | everything arriving from outside |
| `power.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `power.events` | the audit trail, and what the projector and SSE stream read |
| `power.approvals` | an agent needs a person; resumes a checkpointed graph |
| `power.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `live:power` | mains, battery and runtime, read by the tray every second |
| `owned:{pid}` | the ownership registry — the only PIDs this may signal |
| `lock:plan` | one custodian acting at a time |
| `idem:event:{id}` | a flapping supply emits the same transition repeatedly |

**Postgres:** `readings, jobs, plans, actions, outages, events` — `outages` is what the finding is computed from.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): A system-tray applet with a timeline page — the only honest shape for something that has to work while the screen is off.

## Real data

This machine. UPS or battery state via the OS, GPU load via `nvidia-smi`, and the real job table: model pulls, training runs, prefetches.

## The deterministic core

`src/powerguard/domain.py` decides what to do when the power goes, in what order, and — above all — which processes it is allowed to touch. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 12_powerguard
python -m pytest -q                      # 48 passed
PYTHONPATH="src;../platform/src" python -m powerguard.app    # console on http://127.0.0.1:8000
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

- **It never signals a process it did not start.** Other chat sessions train on this box. Unowned jobs at risk are reported to you and left alone. This is enforced in the planner, not in a comment.
- **It does not decide policy with a model.** Thresholds are numbers in a config file.
- **It does not force-kill.** Checkpoint, then request a stop, then wait. A `TaskStop` that does not kill a process tree is a known behaviour here, not a surprise.
- **It does not resume a job you disabled**, however idle the machine gets.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `battery_pct`, `claims`, `issued_receipts`, `jobs`, `minutes_remaining`, `on_mains`

Published to `power.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `actions`, `actions_taken`, `battery_pct`, `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `draft`, `drop_rate`, `dropped_claims`, `incident_note`, `issued_receipts`, `jobs`, `kept_claims`, `minutes_remaining`, `model`, `on_mains`, `receipts_source`, `summary`, `summary_subject`, `unowned_at_risk` |

**The early exit**, on a payload that trips `nothing_to_do`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
