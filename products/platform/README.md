# agentplatform

The shared platform the twenty products in [`../`](../) sit on.

**Nothing is required to import this package** — no broker, no database, no model, no
framework. FastAPI, LangGraph and ollama are optional extras behind lazy imports. The nine
skipped tests are the contract suite against a real Redis, Postgres and Kafka; the nine
LangGraph ones skip too when that extra is absent, each naming the package rather than
pretending the feature is untested for some other reason.

```
python -m pytest -q                      # 150 passed, 9 skipped
```

## What is here

| Module | What it decides | Why it is not in a prompt |
|---|---|---|
| `topics` | the five topics per product, and which partition a key lands on | per-entity ordering is a correctness property, not a hint |
| `keys` | the six Redis keys and the TTL each must carry | a key without a TTL is a leak; a lock without one is an outage |
| `authority` | which agent may write which field | an agent that *can* write the record will eventually write something wrong |
| `gate` | which claims reach the user | a model cannot be asked to mark its own fabrications |
| `admission` | how many model workers this GPU can run | the bus has twelve partitions; the card has one model |
| `memory` | which facts are persisted | ungated writes are why long-lived agents rot |
| `ports` | the bus, store and cache as protocols, with in-memory implementations | a product must run end to end in a test |
| `models` | which model a product actually gets, and which one it was | nothing waits on a download |
| `llm` | the model interface, a fake, and the cache and budget wrappers | a test must not be able to reach a real model by accident |
| `graphs` | the graph runtime: five shapes, checkpointed interrupts | two measured findings are enforced, not suggested |
| `api` | the four things a person does with an agent product | — |
| `blueprint` | the seven-node shape all twenty products share | writing it twenty times means twenty places for the approval gate to be subtly wrong |
| `adapters` | Redis, Kafka and Postgres behind the ports | — |
| `web` | the operator console every product serves at `/` | — |

## The graph runtime, and LangGraph

A graph is declared as data — nodes, edges, and which node is an interrupt. It runs today on
`graphs.run()` with nothing installed, and `graphs.to_langgraph()` compiles the same
declaration onto LangGraph once the extra is present. A product describes its graph once
either way.

That sentence was false of three things at once, and `to_langgraph` had no test of any
kind. An interrupt node and a fan-out node both carry no `run` function — the pause and the
branch set *are* their bodies — and the compiler substituted `lambda s: {}` wherever `run`
was missing. So **the approval gate was compiled out of every product's graph**, and so was
the branch status list, which is the one thing the fan-out exists to guarantee. Separately,
`StateGraph(dict)` has no reducer, so each node's return replaced the channel set instead of
adding to it: a two-node graph seeded with `{"seed": 0}` came back as `{"y": 1}`.

Each node now returns the merged state, a fan-out runs the branch set, and an interrupt
compiles to LangGraph's `interrupt_before` on the node behind it, with a checkpointer
supplied if the caller has none:

```python
app = graphs.to_langgraph(graph)
config = {"configurable": {"thread_id": run_id}}
app.invoke(state, config)   # runs to the gate and stops; nothing behind it has run
app.invoke(None, config)    # the approval; resumes after the gate
```

An interrupt whose outgoing edge is conditional, or which leads straight to `END`, has no
named node to pause before. That is refused with an error rather than compiled into a graph
with no gate in it.

Two findings from `langgraph-lab` are enforced in the runtime rather than written in a
prompt:

- **A fan-out always hands the next node the branch status list.** A silently failed branch
  was disclosed 0% of the time by a default synthesis prompt, so `branch_status` and
  `branches_failed` are in the state and cannot be missed.
- **A resumed run restarts at the node *after* the interrupt.** A naive pause-and-reinvoke
  wastes exactly one generation per approval — a flat 50% overhead for identical output.
  There is a test asserting the drafting call happens once across a pause and a resume.

`graphs.loop()` caps revision at two iterations by default, with an **external** done
predicate, because doubling a critique-revise loop from three to six changed nothing on
every task measured and self-reported completion quit on the first draft every time.

## A budget charged what a call might cost

`admission.Controller.admit` added `len(prompt.split()) + max_tokens` to a tenant's
usage, and nothing ever corrected it. `used()` was a sum of worst cases, reported as
consumption. A 19-word prompt answered in four tokens stood at 515 — **129 times what it
cost** — so a 100,000-token daily budget allowed 194 calls where the real usage allows
25,000, and the tenant hit its limit having spent 0.4% of it. A cache hit, which reaches
no model at all, was charged in full.

An admission now **reserves** the estimate and the release **settles** it:

```python
decision = controller.admit("acme", estimate)   # reserved, and counted against the budget
...                                             # the generation runs
controller.release(decision.reservation, completion.total_tokens)
```

Reserving still has to happen before the call — two concurrent generations must not both
fit a budget that one of them would exhaust — and usage is reported in three parts because
they are three different claims:

| | |
|---|---|
| `settled(tenant)` | tokens the model reported consuming |
| `estimated(tenant)` | an estimate nothing reconciled: a generation that raised |
| `reserved(tenant)` | held by generations still running |
| `used(tenant)` | all three, which is what the budget is checked against |

A call that raised keeps its estimate charged, because the safe assumption about an
unmeasured call is not that it was free — but it is booked as an estimate rather than as
measured usage, so the two cannot be confused.

## Nothing waits on a download

`models.resolve(role, installed)` hands back the best installed model for a capability and
records which one it was. A product asking for `general` gets `qwen2.5:7b-instruct` today
and `qwen2.5:14b-instruct` once that lands — and `Resolved.note` says which, so a later run
is a comparison row rather than an overwrite. `models.comparison_pending()` names the model
whose arrival would be worth re-running for.

## Three decisions worth the space

**Partitioning uses `zlib.crc32`, not the built-in `hash`.** Python salts `hash` per
process, so a consumer restarted tomorrow maps the same key to a different partition and
silently loses the per-entity ordering the whole design rests on. There is a test pinning
this.

**Authority is default-deny.** Anything not explicitly granted is `NEVER`, so a column added
to the schema next month is closed rather than open.

**The gate checks for invented receipts, not just missing ones.** A claim citing `src_z99`
when no such receipt was issued looks exactly like a real citation to a human reviewer.

And one more, in `llm.Recorded`: an unscripted prompt **raises**. A fake that answers
plausibly is how a test stops testing anything, and it is also how a test suite quietly
starts calling a real model.

## Scope

- **No Kafka, Redis or Postgres client.** `ports.py` defines the protocols; binding them is
  a deployment concern and the `infra` extra names the libraries. The nine skipped tests
  are the contract suite run against the real three, and each one **names why it skipped**
  — a missing client library and an unreachable service used to be the same message. The
  extra declared `confluent-kafka` while the adapter imports `kafka`, so on a machine with
  a healthy broker those tests skipped saying `no broker on localhost:9092`.
- **No LLM call anywhere in the tests.** `llm.Ollama` is the only thing that would, and it
  is never constructed in one.
- **No async.** The runtime is synchronous. FastAPI's handlers are the only async surface
  and they do not need to be.
- **No retry, backoff or circuit breaking.** That is the client library's job.
- **No scheduler.** `Runtime.drain()` is one worker pass; what calls it in production is a
  supervisor, not this package. It reports `done`, `failed` and `awaiting_approval` rather
  than a count of messages taken off the topic — that count was the same number for a pass
  that completed every run and one that sent every run to the dead-letter queue.

## At-least-once, and what made it so

`Bus.commit` was declared in the protocol and called nowhere. `poll` advanced the
committed offset itself, so a worker that read a batch and then died had consumed it:
nothing would hand those messages back. The module docstring in `adapters/kafka_bus.py`
said "a worker that crashes mid-generation must redeliver, not skip" and the platform
delivered the opposite.

There are two cursors now. `position` is how far a consumer has read; `committed` is how
far it has acknowledged. `restart()` drops the first and keeps the second, which is the
only way a test can observe the difference:

```python
bus.publish("crm.tasks", "deal:1", {"n": 1})
bus.poll("crm.tasks", "workers")        # read
bus.lag("crm.tasks", "workers")         # 1 - reading is not finishing
bus.restart("crm.tasks", "workers")     # the worker died
bus.poll("crm.tasks", "workers")        # delivered again
```

`lag` counts what is unacknowledged rather than unread, so a batch in flight no longer
reads as caught up. `Runtime.drain` commits the batch when it is done with it, and
`KafkaBus.commit` honours the partition offsets it is given — it used to accept them and
call `consumer.commit()` regardless, which acknowledged the whole batch when a worker
handed back only the part it had finished.

## Input / Output

Measured on a local GPU, 2026-09-20, Quadro RTX 5000 16 GB, `qwen2.5:14b-instruct` at Q4
via ollama:

| | |
|---|---|
| Generation | **33.7 tok/s** |
| Prefill | **304.8 tok/s** |
| Cold load, contended | **683.5 s** — waiting for `qwen2.5-coder:14b` to be evicted, then 9 GB from disk |
| Reload, second call | **254.3 s** — it had been evicted again in between |

Two things follow, and both are why this package is shaped as it is.

**A 14B↔14B swap costs four to eleven minutes on this box.** Two 14B models do not fit in
16 GB together — 9.0 GB each — so ollama evicts one to load the other. Coder work and
instruct work cannot be interleaved; they have to be scheduled apart. `admission.Gpu` says
`max_slots` from VRAM for exactly this reason, and the model was in fact evicted twice
during the two measurement calls above.

**A seven-node graph makes two generations.** At 33.7 tok/s a 500-token draft is ~15
seconds, so one product run is roughly half a minute of GPU time. That is the number the
bus exists to absorb: the UI accepts work in milliseconds and the card serves it at 33.7
tok/s whatever the queue looks like.

The `kv_cache_mb_per_slot = 3000` in the admission tests is still a placeholder and is
labelled as one; deriving it needs a concurrency sweep, which is `swarm-lab`'s job.
