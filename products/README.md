# Twenty products

Twenty multi-agent products on one platform. Each is an operator console over a real API,
over a real event bus, over a real store, driven by a local instruct model under a graph
runtime, with a named hallucination gate that can be measured.

Distinct from [`../projects`](../projects), which holds eleven finished single-purpose
tools. These are products: several agents, a bus, a store, an approval loop, a UI.

**Status: all twenty run end to end.** HTTP in → onto the bus → drained by a worker →
paused for approval → resumed without regenerating → committed. Each serves an operator
console at `/`. The full design for each — agent roster, topics, Redis keys, schema, demo
data — is in its own README.

```
python -m venv .venv && .venv/Scripts/pip install -e platform[api,infra] pytest ruff
cd platform        && python -m pytest -q     # 127 passed, 9 skipped
cd 01_revenue-desk && python -m pytest -q     #  37 passed, 1 skipped

python scripts/capture.py       # runs all 20 for real, writes scripts/runs.json
python scripts/smoke_serve.py   # boots all 20 on uvicorn, writes scripts/served.json
python scripts/make_invoices.py # one-off: Online Retail II -> invoice totals
python scripts/make_prices.py   # one-off: Online Retail II -> product prices
python scripts/screenshots.py   # real captures of the running console
```

Every Input/Output section in the twenty READMEs is written from `scripts/runs.json`,
which is a real intake → drain → approve cycle. None of those figures were typed by hand.

**Every suite green, and the skips are reported rather than folded in.** On a machine
with Kafka, Redis and Postgres running, the nine contract tests in `platform` execute
against them; without those services they skip and say so, which is why a count quoted
here would be a different number on your machine than on mine. `python ../scripts/test_all.py`
prints what ran and what skipped, and refuses to call an all-skipped suite green.
Every product reads a real dataset. The datasets are
committed under [`data/`](data) — OFAC's sanctions lists, Loghub, Synthea, AMI, LoCoMo,
OSV, HotpotQA, eCFR, TSPLIB, NCBI GenBank, UCI Online Retail II and seventeen RFCs.

**All 20 also boot on a real ASGI server**, not just a test client:

```
python scripts/smoke_serve.py      # 20/20 products served over HTTP
```

That starts uvicorn for each product in turn and drives a full intake → drain → approve
cycle over HTTP, so "it serves" is something that was observed rather than assumed. The
result is written to `scripts/served.json`.

## The twenty

Each product reads a real dataset and has produced the number it exists to produce. No
figure below was typed by hand; each is asserted by a test that runs the code over the data.

| # | Product | Real data | What it measured |
|---|---|---|---|
| [01](01_revenue-desk) | [**revenue-desk**](01_revenue-desk) | 1,601,517 line edits across 74 git repos, frozen as a fixture | Generated files are **92.5% of reverts**; the code rate is **9.36x** lower, and prose turned out to need separating from code too |
| [02](02_ward-sync) | [**ward-sync**](02_ward-sync) | 3,850 Synthea prescriptions | **93% of prescriptions end**; a "current list" is **5.5x too long** for 104 of 105 patients |
| [03](03_one-desk) | [**one-desk**](03_one-desk) | 300 AMI summaries + 48 real 14B generations | The human baseline is **0.073 wide** (p<0.0001); four variants differ as much as two people do |
| [04](04_ledger-brain) | [**ledger-brain**](04_ledger-brain) | 54,716 real invoices | **Half** share an amount with another; matcher accuracy on that half is **33.7%** |
| [05](05_comms-desk) | [**comms-desk**](05_comms-desk) | 104,923 AMI dialogue acts, all 139 meetings | Ignoring who spoke makes 786 merges, **686 of them wrong** |
| [06](06_oncall-mate) | [**oncall-mate**](06_oncall-mate) | 32,000 Loghub lines, all 16 systems | Compression ratio spans **115x** with the templater fixed; median is **8.5x**, not 11 |
| [07](07_hire-desk) | [**hire-desk**](07_hire-desk) | 5,882 real conversation turns | After redacting 1,971 names, **"Mel" survives 59 times** |
| [08](08_bid-desk) | [**bid-desk**](08_bid-desk) | 4,036 RFC 2119 requirements, 17 RFCs | Recall is **1.000**; precision **0.827** — the asymmetry runs the other way |
| [09](09_hermes-home) | [**hermes-home**](09_hermes-home) | LoCoMo, 1,982 questions | Median answer lives **14 sessions back**; an 8-session window answers **28%** |
| [10](10_kyc-floor) | [**kyc-floor**](10_kyc-floor) | OFAC 8,650 + UN 2,163 labelled aliases | Skeletons buy **+19.8 points for zero precision cost** — and **+18.6 on a second list** |
| [11](11_watchtower) | [**watchtower**](11_watchtower) | 30,098 OSV PyPI advisories | "Below the highest fix" is wrong **15.4%** of the time — and **cannot fire at all** on 39% of them |
| [12](12_powerguard) | [**powerguard**](12_powerguard) | a real process table + 4,000 generated states | **0** actions ever aimed at another session's pid — except hibernate, which reaches everything |
| [13](13_swarm-lab) | [**swarm-lab**](13_swarm-lab) | N workers on real Redis | Uncoordinated waste is exactly **1 - 1/N**; 95% at N=21 |
| [14](14_graph-clinic) | [**graph-clinic**](14_graph-clinic) | all 7,405 HotpotQA questions | Graph wins **4.5x** on bridge questions and finds **1 in 1,000** comparison ones |
| [15](15_claims-floor) | [**claims-floor**](15_claims-floor) | 6,000 eCFR versions, 6 regulators | Returning the current text is wrong **49%** of the time, by a median of **2.5 years** |
| [16](16_shelf-ops) | [**shelf-ops**](16_shelf-ops) | 4,501 real products | Compounding two in-policy discounts breaks **one product in five** |
| [17](17_fleet-desk) | [**fleet-desk**](17_fleet-desk) | 6 TSPLIB instances + proven optima | "Go round the city in a circle" is **92% worse at 52 stops, 181% at 150** |
| [18](18_campus-ops) | [**campus-ops**](18_campus-ops) | 5,571 scheduled events | A room-only checker misses the **9 overlaps that are physically impossible** |
| [19](19_agri-desk) | [**agri-desk**](19_agri-desk) | all 898 NCBI GenBank genomes, 23 countries | **422 emerging variants become 2**; false-alarm rate **0.9954** — and the 2 are real |
| [20](20_driftwatch) | [**driftwatch**](20_driftwatch) | 35 real repositories | **1.64%** of README sentences are machine-settleable; 9.1% of those are false |

### Four of them contradicted their own README

The plan wrote down a prediction for each product before any data was involved. Measuring
overturned four, and the READMEs say so rather than quietly reframing:

- **watchtower** predicted distribution backports as the main source of false positives. The
  real cause is simpler and larger: flagging versions written *before* the bug existed.
- **bid-desk** was designed around "a miss is fatal, a false positive is cheap". Recall
  turned out to be perfect and precision the problem.
- **graph-clinic** predicted the graph would lose to a plain baseline. It wins four and a
  half to one on the bridge questions and finds one comparison pair in a thousand.
- **one-desk** predicted the four platform variants would be near-identical. They are — and
  the human baseline needed to *prove* it was the part that was actually hard.

### Two headline numbers checked against a second, independent source

A number measured on one corpus is a fact about that corpus until something else agrees:

- **kyc-floor** built every figure on OFAC, then ran the same code over the UN Security
  Council list. Over *all* labelled pairs the two disagree by six points; over the pairs a
  spelling rule could reach they agree to within 1.2. The denominator was the whole
  disagreement — OFAC leaves 12% of its aliases unreachable by any spelling rule and the UN
  41%, which is a fact about what each body publishes, not about the matcher. The UN also
  grades its aliases, and 74% of the ones it marks doubtful are unreachable against 27% of
  the confident ones, which confirms by the publisher's own judgement what this product had
  only argued.
- **claims-floor** did the same across six CFR titles and found its rate held and its
  severity did not.

Both also found what does *not* transfer: kyc-floor's screening threshold costs 1.74% false
positives on OFAC and 7.5% on the UN, so the ranking of rules is portable and the cut-off
is not.

### Six found real bugs by being run

- **powerguard** classified 14 jobs on a real workstation; eleven were the interpreter's install
  path matching `\buv\b`. It also produced `checkpoint python.exe` as an instruction, with
  two different `python.exe` processes running — so `Action` now carries a pid and refuses
  to exist without one.
- **agri-desk** read `/country`, which GenBank renamed to `/geo_loc_name`, and silently
  collapsed every country into one stratum. It also counted an unlabelled record as a
  second site, letting a single-site variant clear the multi-site guard by being partly
  unlabelled.
- **driftwatch** caught a live drift in this very repository: the README claims zero runtime
  dependencies while `pyproject.toml` declares thirteen.
- **watchtower** read every `affected` block in OSV's PyPI export, pulling 454 npm, Maven,
  NuGet, crates.io and Go packages into a PyPI scan and ordering Go pseudo-versions with a
  PEP 440 key. It also had no notion that 39% of the database is malicious-package reports
  rather than vulnerabilities.
- **powerguard** guarantees it never signals a process it does not own, and then hibernates
  the whole machine, which reaches every process on it. Found by generating 4,000 machine
  states — it needs a flat battery *and* another session's job at once, which the test machine
  has never been in while anyone looked.
- **revenue-desk** counted committed datasets and regenerated `results.json` files as human
  edits, and read a line moved within a single commit as a revert. Together those made its
  headline an order of magnitude too high — and left it drifting 18% when a dataset was
  committed.

### What is honestly not measured

Three products name a number they have not produced, and say so in their own README:

- **hire-desk** — the identified-versus-redacted score delta. No CV corpus exists here and
  inventing one breaks the no-fabricated-dataset rule.
- **one-desk** — engagement by posting time. That needs the account owner's own history.
- **powerguard** — work lost per outage. No outage has happened while the custodian watched.

## The shared platform

[`platform/`](platform) holds the eleven things every product needs, none of which needs a
model to be correct: the five-topic convention and stable partitioning, the six Redis keys
with their TTLs, default-deny write authority, the grounding gate, GPU admission control,
contradiction-gated memory, the bus/store/cache ports, model resolution, the LLM interface,
the graph runtime and the HTTP surface. Build on it rather than rebuilding it twenty times.

Three of those eleven are available rather than wired in. **`memory`** and
**`admission`** are not imported by any product. **`authority`** is imported by all twenty
— to build the table — and its `check`, `apply` and `level_for` are called nowhere outside
`authority.py` itself, so no request is ever refused by it. Each of the three is
implemented and tested here; none is on a path a request takes. An independent review
found that by grepping for callers, which is a fair way to read "every product needs", and
the sentence above is the one that had to change rather than the grep.

Four of its decisions are worth knowing before reading any product:

- **Partitioning uses `zlib.crc32`, not the built-in `hash`,** which Python salts per
  process. A consumer restarted tomorrow would otherwise map the same key to a different
  partition and silently lose per-entity ordering.
- **Authority is default-deny**, so a column added to a schema next month is closed rather
  than open.
- **The gate catches invented receipts, not just missing ones.** A claim citing `src_z99`
  when no such receipt was issued looks exactly like a real citation to a reviewer.
- **`llm.Recorded` raises on an unscripted prompt.** A fake that answers plausibly is how a
  test stops testing anything — and how a suite quietly starts calling a real model.

## LangChain, LangGraph and the API layer

A graph is declared as data — nodes, edges, and which node is an interrupt. It runs today on
`graphs.run()` with nothing installed, and `graphs.to_langgraph()` compiles the same
declaration onto LangGraph once that extra is present. A product describes its graph once
either way, so **LangGraph is a deployment choice rather than a rewrite**.

It is now. `to_langgraph` had no test, and an interrupt node and a fan-out node both carry
no `run` function — the pause and the branch set *are* their bodies — so the compiler's
`lambda s: {}` fallback compiled **the approval gate out of every product's graph**, along
with the branch status list below. `StateGraph(dict)` also has no reducer, so state did not
accumulate between nodes at all. Nine tests in
[`platform/tests/test_langgraph.py`](platform/tests/test_langgraph.py) now hold the compiled
graph to the runtime's behaviour; eight of them failed against the old compiler.

Two measured findings are enforced in the runtime rather than written into a prompt:

- **A fan-out always hands the next node the branch status list.** A silently failed branch
  was disclosed 0% of the time by a default synthesis prompt, so `branch_status` and
  `branches_failed` are in the state and cannot be missed.
- **A resumed run restarts at the node *after* the interrupt.** A naive pause-and-reinvoke
  wastes exactly one generation per approval — a flat 50% overhead for identical output.

`api.Runtime` is the worker and the write path; `api.create_app()` is FastAPI over it. Four
routes, because there are four things a person does with an agent product: start work, watch
it, approve what it paused on, read the audit trail. **`/intake` publishes and returns** —
it does not run the graph, which is the entire argument for the bus.

`01_revenue-desk` is the worked example: every graph shape appears in it exactly once, and
there is a test asserting that.

## Nothing waits on a download

`models.resolve(role, installed)` hands back the best installed model for a capability and
records which one it was. While `qwen2.5:14b-instruct` was still downloading, a product
asking for `general` got `qwen2.5:7b-instruct` and `Resolved.note` said so; the 14B landed
on 2026-09-20 and the same call now returns it. Nothing had to be rewritten, and the earlier
runs stay valid as a comparison row rather than being overwritten.

That is the point of the indirection: **no product was ever blocked on an 8.6 GB download
that died five times.**

## The console

Every product serves the same operator console at `/`. One HTML file, no build step, no
npm, no framework — light and dark, and it works at phone width. Four things, because there
are four things a person does with an agent product:

| | |
|---|---|
| **Start work** | posts to `/intake`, which publishes and returns. The GPU is not touched. |
| **Watch it** | `/runs` — status, nodes visited, model calls spent |
| **Approve what paused** | `/approvals` — shows what the run has *already* cost before you decide |
| **Read the trail** | `/events` — peeked, never consumed, so it does not steal from the projector |

Deliberately one shared console rather than twenty frontends. Twenty half-implemented
dashboards is the mistake this portfolio already made once and corrected by deleting them;
there are tests asserting the page renders, that no `{{placeholder}}` survives, and that
every route the page calls actually exists.

## Running the infrastructure

`docker-compose.yml` brings up Postgres, Redis and Kafka. The model server is **not** in
it: ollama runs on the host, because it needs the GPU.

```
docker compose up -d
```

`adapters/` binds the ports to the real thing — `RedisCache`, `KafkaBus`, `PostgresStore`.
The contract tests in `platform/tests/test_contract.py` run the *same* assertions against
the in-memory implementations and against these, and skip the real ones when the service is
down. A contract test that only ever runs against a fake is a test of the fake.

Two bugs that only a real broker could have found, both now fixed and both with a test:

- **A brand-new consumer group returns nothing on its first poll** while the coordinator is
  assigning partitions. Treating that empty batch as "no messages" makes a first-run worker
  process nothing and commit.
- **The polls that establish assignment also fetch records.** Discarding them loses the
  first batch entirely — assignment succeeds, messages gone. `KafkaBus` buffers them.

## Measured on a local GPU

2026-09-20, Quadro RTX 5000 16 GB, `qwen2.5:14b-instruct` at Q4:

| | |
|---|---|
| Generation | **33.7 tok/s** |
| Prefill | **304.8 tok/s** |
| Cold load, contended | **683.5 s** |
| Reload after eviction | **254.3 s** |

Two 14B models do not fit in 16 GB together, so ollama evicts one to load the other — it
happened twice during those two calls. **Coder work and instruct work cannot be
interleaved on this box.** A seven-node graph makes two generations, so one product run is
roughly half a minute of GPU time; the bus is what lets the console stay responsive while
the card works through the queue.

## Why the consumer group is smaller than the partition count

One card, 16 GB, one model instance. A six-agent workflow is six *sequential* generations,
so the topic can have twelve partitions while the consumer group that calls the model has
two. `platform/admission.py` computes that from VRAM rather than leaving it to a config
file someone will copy from a blog post.

This is also the whole reason the bus is load-bearing rather than decorative: it lets the
UI accept two hundred requests while the GPU serves them at its own pace, and it survives a
worker dying mid-generation.

## Standing constraints

- **Nothing here waits on a 14B.** Every product must be demonstrable on
  `qwen2.5:7b-instruct`, with a larger model added later as a comparison row — the pattern
  the model-comparison work already uses. A product whose demo cannot run today is not on
  the critical path.
- **Every README carries "what it does NOT do" and "problems hit while building this".**
- **Every README also says where Kafka is load-bearing and where it is not.** Bolting a bus
  onto something that does not need one is the commonest way this kind of product reads as
  unserious.
- **No number appears in a README that was not produced on a machine.** Every product's
  Input/Output section currently says it has produced none, because it has not.
- **Findings over features.** Each product names the number it exists to produce, and ships
  that number even when it contradicts the product.
