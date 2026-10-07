<h1 align="center">agentic-ai-llm</h1>
<p align="center"><i>Ten measurement tools for local coder models, eleven standalone developer tools, and twenty agent products on one shared platform.</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/apps-10-e879f9" alt="apps">
  <img src="https://img.shields.io/badge/bus-Kafka-231f20" alt="kafka">
  <img src="https://img.shields.io/badge/state-Redis-dc382d" alt="redis">
  <img src="https://img.shields.io/badge/orchestration-LangGraph-1c3c3c" alt="langgraph">
  <img src="https://img.shields.io/badge/model-qwen2.5--coder-orange" alt="model">
</p>

---

Benchmark numbers are easy to quote and hard to act on. These ten apps each answer one
question that changes what you would build: whether the bigger model earns its VRAM, when to
stop a retry loop, whether generated tests catch anything, and how much of a published score
belongs to the prompt rather than the model.

Every one is a real web application with its own visual identity, backed by a Kafka job bus,
Redis state and a worker that owns the single GPU.

## The ten

| # | Icon | App | Question | Theme |
|---|:-:|---|---|---|
| [**01**](apps/01_localizer) | 🧭 | [**Localizer**](apps/01_localizer) | which file does this issue touch? | deep ocean |
| [**02**](apps/02_false_accepts) | 🧫 | [**False Accepts**](apps/02_false_accepts) | how much wrong code do three asserts let through? | crimson lab |
| [**03**](apps/03_vuln_baseline) | 🛡 | [**Vuln Baseline**](apps/03_vuln_baseline) | can a model beat answering "safe" every time? | amber terminal |
| [**04**](apps/04_size_curve) | 📐 | [**Size Curve**](apps/04_size_curve) | where does a 5× bigger model actually pay? | violet |
| [**05**](apps/05_debug_ceiling) | 🌿 | [**Debug Ceiling**](apps/05_debug_ceiling) | how many rounds of self-debugging are worth it? | forest, light |
| [**06**](apps/06_kill_rate) | 🎯 | [**Kill Rate**](apps/06_kill_rate) | do model-written tests catch anything? | magenta |
| [**07**](apps/07_repair_rewrite) | 🔀 | [**Repair or Rewrite**](apps/07_repair_rewrite) | patch the failure, or start over? | slate & coral, light |
| [**08**](apps/08_prompt_shapes) | 🖋 | [**Prompt Shapes**](apps/08_prompt_shapes) | how much of a score is the wording? | teal paper, light |
| [**09**](apps/09_temperature) | 🌡 | [**Temperature Lab**](apps/09_temperature) | where do pass@1 and pass@k diverge? | heat |
| [**10**](apps/10_roundtrip) | 📜 | [**Roundtrip**](apps/10_roundtrip) | what survives code → prose → code? | sepia, light |

Ten palettes, four light and six dark, drawn from **five** display/body typeface pairings
and **nine** distinct corner radii — opening two of them side by side should not feel like
opening the same tool twice. (This said "their own typeface pairings", which reads as ten:
four themes share Inter with Inter, two share Source Serif with Source Serif, and all ten
share one monospace. The light/dark split is exact.)

## What they found

Every number below was measured, not estimated — each is the output of the app above it,
run locally on `qwen2.5-coder` at 14B and 3B over MBPP, HumanEval, SWE-bench and Devign.
**The run artifacts are not committed**: reproducing one needs Ollama, both model sizes and
a GPU, so they are a claim about work done on this machine rather than something this
repository can show you.

What it can show you offline is the measurement code, every execution rule it applies, and
the eleven tools in [`projects/`](projects), whose numbers you can reproduce by running
them. "The measurement code" was a set of pieces until recently: `print_report`,
`commit_listings`, `listing_for` and `find_many` had no caller anywhere here, which is
the fingerprint of a driver that ran on this machine and was never committed. It is
committed now, and **the BM25 row of the localization table is reproducible with no model
and no network**:

```bash
python -m apps._engine.localize_eval     # all 300 instances, ~30s, no model, no network
```

It reports the population it scored and the instances it could not. The one instance
whose gold file is absent from its repository listing is **kept** in the denominator and
scored as a miss: nothing can retrieve a file that is not there, so excluding it would
flatter every retriever equally and by an amount nobody could see. So the denominator is
154 and not 153, and the rate is 8.4% and not 8.5%. This paragraph used to state the
opposite rule - the flattering one - while every figure below it was computed under this
one. The two model arms and the dense arm are flags on the same command.

That command used to work only here. It read SWE-bench Lite out of a Hugging Face cache,
and on a machine without one it raised `FileNotFoundError` — while the four tests that
verify its numbers skipped in exactly that condition, so the one claim offered as
checkable by a stranger was checkable only by its author. Worse, `HF_HOME` and
`HF_HUB_CACHE` were *appended to* the default rather than replacing it, in three separate
copies of the same resolver, so pointing one at an empty directory isolated nothing and
every offline check was reading the real cache.

The columns these apps read are committed under
[`data/benchmarks/`](data/benchmarks) — 2.8 MB, beside the 460 KB of tree listings in
`data/trees` that are committed for the same reason. `tests/test_hermetic.py` asserts the
guarantee by pointing both variables at an empty directory, and the suite gives the same
result either way: **1,057 tests collected**. Measured 2026-10-07, 963 of them pass and 94
skip here; on a fresh clone the split moves because three suites read data that is not in
the repository.

That figure said "317 passed, 38 skipped" for a long time, against a suite that was
already collecting more than twice that. Nothing checked it:
`tests/test_documented_counts.py` sweeps `projects/` and `products/`, so the module whose
whole job is catching a drifted count had a blind spot at the repository's own front
door - and this paragraph then described the correction with three different numbers,
none of which was the one being asserted.

The collected figure above is asserted against `pytest --collect-only`, which is the only
form of this claim a suite can check about itself: a suite cannot assert its own pass and
skip counts without running itself, so the two figures beside it are measured and dated
rather than pinned. `scripts/test_all.py` runs the root suite too, so a fresh-clone
failure in it shows up beside the other 32.

`repo-cartographer`'s resolution table is the last three lines of
`cartographer compare <folder>` over every checkout in one folder — it used to
quote a median across a chosen 29 that nothing in the tool computed, and the five JSONs
shipped beside it covered five of those rows.

- **BM25 collapses from 75% (38 of 51) to 8.4% (13 of 154)** depending only on whether the
  issue quotes the file path. The same 14B model scores 55.8% on that hard half when naming files freely and
  **17.5% when restricted to reranking** — its advantage is knowing the repository, not
  reading the issue. The fabrication rate that used to be quoted here — "one path in
  five" — is withdrawn: it was measured with a parser that read a bolded, quoted or
  line-numbered path as a path that does not exist, so part of that fifth was this
  harness failing to read an answer rather than the model inventing a file. The parser
  now reads the shapes a model actually returns and `fabrication_rate` reports
  `lines_unparsed` beside the rate, so the two can no longer be summed. The figure
  returns when the arm is re-run.
- **Devign's always-SAFE baseline is 54.1%**, against published accuracies around 62% —
  eight points of headroom, not sixty-two. The model figure this line used to quote was
  measured against the first 800 rows of the file, which are 49.6% safe rather than 54.1%,
  and was then compared against the *majority* class on that sample, which is VULNERABLE.
  The comparison therefore ran the wrong way round. The app now samples the split with a
  seed and returns both constants; the model number is pending a re-run.
- **18.0% of 4,055 single-point mutants survive MBPP's three asserts**, and 362 of them are
  provably wrong — half the survivors; the rest are reported unproven rather than counted.
  Hand-verification does not fix it: the sanitized split scores 16.5%.
- **Self-debug rounds 1–2 captured 100% of the gain**; rounds 3–5 added zero tasks for 60%
  of the compute. Independently: **93.3% of first-attempt failures survive both** repair and
  rewrite.
- **The 3B already handles 75.8%** of everything either size can solve.
- **Generated tests beat the benchmark's own** — 93.4% kill rate against 85.0% — but only
  when written from the implementation. From the task description, just 16% even agree with
  the reference.
- **Describing the reference code and reimplementing from that beats MBPP's own description
  by 32.5 points.** That is a leak, not better documentation — and 32.5 is an upper bound
  on it. App 10's description-only baseline is the one place in this repository that does
  not hand the model one of MBPP's own asserts, which is why app 04 reports the same 14B
  at 76.0% on the task description where app 10 reports 48.0%. A `direct_with_test` arm
  now sits between them; the share of the 32.5 that is the assert rather than the leak is
  unmeasured until it runs.

## Architecture

```
browser  ──POST /run──▶  FastAPI (one per app, ports 8001-8010)
                          │
                          ├─▶ Kafka  jobs.requested    partitioned by app
                          │            │
                          │            ▼
                          │         worker.py  ──▶  Ollama, 8 requests in flight
                          │            │
                          │            ├─▶ Redis  generation cache, shared by all ten
                          │            ├─▶ Redis  job state + pub/sub
                          │            └─▶ Kafka  jobs.completed   kept for a year
                          ▼
browser  ◀──SSE────────  Redis pub/sub
```

**The web process never runs a measurement.** A submit publishes and returns a job id; the
worker consumes the partition and streams ticks back.

**Why a log and not a task queue.** `jobs.completed` is the durable record of every
measurement ever run here. Re-reading it from offset zero rebuilds the results without
re-running a single generation — which matters when a run costs an hour of GPU. The history
page in every app does exactly that.

**Why one worker.** One GPU means one job at a time. Making that explicit beats letting ten
web processes each start a run and discover the constraint by thrashing VRAM. Partitioning
by app keeps a long sweep from starving a short one — which needed
`KAFKA_NUM_PARTITIONS: 10` in compose to be true. It was unset, so the broker's default
of **one** applied and all ten apps shared a single FIFO queue: the exact opposite of the
claim, with nothing in the repository to say so.

**Redis is load-bearing, not decoration.** Several apps ask the model identical questions —
the first-attempt prompt in Repair-or-Rewrite is the same one Size Curve sends. Keyed on
`(model, prompt, temperature, seed)`, the second app pays nothing. That is the difference
between clicking through ten tools on one GPU and waiting for each.

**LangGraph where the shape fits.** Debug Ceiling runs its loop as a state graph —
`generate → execute → repair → execute` with a conditional edge on the test result and the
round cap as a recursion limit — because that is what a self-debug loop is. The conditional
reads a real assertion outcome, not a model's opinion of its own work.

Everything degrades. If Kafka is down the job runs in-process and the UI says so; if Redis
is down the apps still work, holding job state and progress in the process that is running
the job — which is the same process, because no Kafka means no worker. The generation cache
is the only thing genuinely lost, and jobs do not survive a restart. A demo that only runs
with the full stack up is a demo nobody runs.

[`tests/test_platform_degraded.py`](tests/test_platform_degraded.py) is that paragraph as a
test: it submits a run and reads the result back with Redis, Kafka and the model all pointed
at a closed port.

## Running it

```bash
docker compose up -d          # redis + kafka (KRaft, no zookeeper)
uv sync --all-groups
python worker.py              # consumes the bus; needs Ollama
sh serve_all.sh               # ten apps on 8001-8010
```

Needs Ollama with `qwen2.5-coder:14b`, plus `:3b` for Size Curve and `nomic-embed-text` for
Localizer. MBPP, HumanEval, Devign and SWE-bench Lite load from the local Hugging Face
cache; nothing downloads at runtime.

## The eleven agent-infrastructure tools

In [`projects/`](projects). Zero runtime dependencies and zero LLM calls — each one is
built around something that turned out to be wrong.

| # | Tool | What it does |
|---|---|---|
| [**01**](projects/01_repo-cartographer) | [**repo-cartographer**](projects/01_repo-cartographer) | Map an unfamiliar Python codebase from its AST — no embeddings, no model |
| [**02**](projects/02_test-smith) | [**test-smith**](projects/02_test-smith) | Mutation testing from the standard library: does the suite catch the change, or merely run it? |
| [**03**](projects/03_review-bot) | [**review-bot**](projects/03_review-bot) | Propose findings, then try to disprove each one. Report only what survives |
| [**04**](projects/04_migration-pilot) | [**migration-pilot**](projects/04_migration-pilot) | Modernise Python where the rewrite is provably equivalent, and refuse where it would change behaviour |
| [**05**](projects/05_release-captain) | [**release-captain**](projects/05_release-captain) | Release readiness scored from diff statistics, not from opinion |
| [**06**](projects/06_db-surgeon) | [**db-surgeon**](projects/06_db-surgeon) | Prove a migration's rollback on a throwaway copy before trusting it |
| [**07**](projects/07_compliance-auditor) | [**compliance-auditor**](projects/07_compliance-auditor) | Stated policy checked against collected evidence. No inferred compliance |
| [**08**](projects/08_csv-analyst) | [**csv-analyst**](projects/08_csv-analyst) | Profile a CSV, compute only what validates, and never narrate a number that was not computed |
| [**09**](projects/09_log-detective) | [**log-detective**](projects/09_log-detective) | Extract log templates, and report what the extraction destroyed |
| [**10**](projects/10_contract-reader) | [**contract-reader**](projects/10_contract-reader) | Read a licence, and cite the character span behind every claim |
| [**11**](projects/11_study-tutor) | [**study-tutor**](projects/11_study-tutor) | Spaced repetition where the scheduler is arithmetic and the model only writes questions |

## The twenty business agents

In [`products/`](products), on a ports-and-adapters platform with its own five-topic Kafka
convention. Each one is measured against real data — the full table with every finding is in
[`products/README.md`](products/README.md).

| # | Agent | # | Agent |
|---|---|---|---|
| [**01**](products/01_revenue-desk) | [**revenue-desk**](products/01_revenue-desk) | [**11**](products/11_watchtower) | [**watchtower**](products/11_watchtower) |
| [**02**](products/02_ward-sync) | [**ward-sync**](products/02_ward-sync) | [**12**](products/12_powerguard) | [**powerguard**](products/12_powerguard) |
| [**03**](products/03_one-desk) | [**one-desk**](products/03_one-desk) | [**13**](products/13_swarm-lab) | [**swarm-lab**](products/13_swarm-lab) |
| [**04**](products/04_ledger-brain) | [**ledger-brain**](products/04_ledger-brain) | [**14**](products/14_graph-clinic) | [**graph-clinic**](products/14_graph-clinic) |
| [**05**](products/05_comms-desk) | [**comms-desk**](products/05_comms-desk) | [**15**](products/15_claims-floor) | [**claims-floor**](products/15_claims-floor) |
| [**06**](products/06_oncall-mate) | [**oncall-mate**](products/06_oncall-mate) | [**16**](products/16_shelf-ops) | [**shelf-ops**](products/16_shelf-ops) |
| [**07**](products/07_hire-desk) | [**hire-desk**](products/07_hire-desk) | [**17**](products/17_fleet-desk) | [**fleet-desk**](products/17_fleet-desk) |
| [**08**](products/08_bid-desk) | [**bid-desk**](products/08_bid-desk) | [**18**](products/18_campus-ops) | [**campus-ops**](products/18_campus-ops) |
| [**09**](products/09_hermes-home) | [**hermes-home**](products/09_hermes-home) | [**19**](products/19_agri-desk) | [**agri-desk**](products/19_agri-desk) |
| [**10**](products/10_kyc-floor) | [**kyc-floor**](products/10_kyc-floor) | [**20**](products/20_driftwatch) | [**driftwatch**](products/20_driftwatch) |

**The `products/` platform and the `apps/` platform are separate, and they are not
duplicates** — a claim this README used to make about itself and which does not survive
being checked. They share no module name beyond `__init__.py` and exactly one public symbol
name, `create_app`, which is the FastAPI convention rather than shared code.
[`apps/_platform`](apps/_platform) is the substrate the ten measurement apps run on: an async
Ollama client that keeps one GPU at ~98% utilisation instead of 9%, a Redis generation cache
shared across apps, a Kafka progress bus and ten themes.
[`products/platform`](products/platform) is the agent runtime: a graph interpreter, the
seven-node blueprint, the approval gate, write authority, admission control and gated memory,
with a model interface whose default implementation *refuses* any prompt it was not given so
a test cannot quietly reach a real model. Different jobs, and merging them would mean one
package with two unrelated reasons to change.

## Limits

- **One model family, one GPU.** Nothing here says how any of it scales.
- **MBPP is mostly short functions.** The self-debug ceiling in particular may look different
  where the first attempt is closer to right.
- **Sample sizes are 20–800** depending on the app, chosen so a run finishes while you watch
  it. Large enough to separate the effects reported; not large enough for small differences.
- **Localizer ranks file paths, not file contents.** Fetching every blob would be a clone by
  another name, so its numbers are a floor for what retrieval can do.
