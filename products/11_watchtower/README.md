# 11 · watchtower

> Vulnerability, exposure and configuration-drift agent for the machines you are authorised to scan.

**Status:** runs end to end. Intake is accepted onto the bus and returns; a worker drains
it; the graph pauses for a person; approving resumes it without regenerating anything. It
serves the shared operator console at `/`.

## Results

**Measured over OSV's published PyPI export** — 30,098 real PyPI advisories across 13,327
packages, each carrying the version ranges it applies to. Every advisory was judged at
every boundary version known for its package: **2,146,007 verdicts.**

| | | |
|---|---:|---|
| Shortcut and interval logic agree | 1,815,314 | 84.6% |
| **False positive** | **304,543** | **14.2%** — flags a version written before the bug |
| False negative | 26,150 | 1.2% — clears a version after the last fix |

**The shortcut is wrong once every six or seven verdicts, and it errs towards false alarms
eleven to one.**

The shortcut is "anything below the highest fixed version is vulnerable", which is what a
scanner does when it reads `fixed_in` and ignores the rest of the advisory. An advisory does
not say *fixed in X*; it says *introduced at A, fixed at B*, sometimes several times over.

A real case, `open-webui` / `GHSA-2724-6cpj-gf3v`, affected range `0.10.0` to `0.11.1`:

- version `0.6.19` is below `0.11.1`, so the shortcut calls it vulnerable
- the vulnerability was introduced in `0.10.0`
- **the bug had not been written yet**

The false negative is the mirror image and matters more per instance: a package with two
maintained branches, broken again at `2.0` after being fixed at `1.2`, sits *above* the
highest fixed version and gets cleared.

### Two fifths of OSV has no fix to be below

**39% of this database — 11,734 records — are not vulnerability reports at all.** `MAL-`
entries are malicious packages: typosquats and backdoored releases. The remedy is removal,
not an upgrade, so **11,729 of the 11,734 carry no fixed version whatsoever.**

The shortcut is "anything below the highest fixed version is vulnerable". Where no fixed
version exists it returns False, always. On malicious packages:

| | |
|---|---:|
| Verdicts | 6,415 |
| **False negatives** | **99.8%** |
| False positives | **0** |

Zero false positives is not accuracy. **It never fires.** For two fifths of OSV the shortcut
is not inaccurate, it is structurally incapable of producing an alert — and the class it
cannot see is the one where the package on your disk is hostile rather than merely flawed.

"Wrong 15% of the time" understates that completely, and the two findings are independent:
drop every malicious record and the headline is 15.2%, because `MAL-` advisories carry few
version boundaries and contribute only 6,415 of 2.1 million verdicts. The range logic
matters for real vulnerabilities; the blindness matters for malware.

### A second thing the export was not

The file is called a PyPI export and contains **454 entries from other ecosystems** — NuGet,
Maven, npm, crates.io, RubyGems, Go — because a GHSA record can list packages in several at
once. Reading every `affected` block pulled them into a PyPI scan, where a Go pseudo-version
like `0.0.0-20231016150651-428517fef5b9` was being ordered by a PEP 440-ish key that means
nothing for it. The loader now filters on ecosystem; it changed the headline by 0.08%, which
is why it went unnoticed, and it was still wrong.

### This contradicts what this README used to predict

The stated hypothesis was distribution backports — a fix applied without bumping the
upstream version. That effect is real and `assess()` still handles it, but it is **not** the
dominant cause. Measuring found something simpler and larger: most spurious flags are
versions that predate the vulnerability entirely. The hypothesis was wrong and this section
says so rather than quietly reframing.

### An honest negative, on the machine that matters

Scanning this environment's 71 installed packages found 31 carrying advisories and 17
genuine findings — and the shortcut and interval logic **agreed on all 17**. A small,
current environment rarely holds a version old enough to sit before an introduction point.
The 14.2% is a property of the advisory population, not a promise about your laptop.

Measured 2026-10-06, and the population moves with the virtualenv: it read "32 installed
packages, 14 carrying advisories" until this was re-run. The conclusion did not move -
17 findings, agreement on all 17 - which is the half worth trusting, and it is why the
figures are now compared against the scan by a test rather than guarded by
`assert len(here) > 10`, a floor that held for 32 and for 71 alike.

Reproduce it:

```bash
cd 11_watchtower && python -m pytest tests/test_real_osv.py -q     # 16 passed, ~70s
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
| `inventory` | `asset.*` | a vulnerability verdict |
| `cve-matcher` | `finding.*` | an exploitability judgement |
| `exploitability-triager` | `finding.priority` | closing a finding |
| `remediation-writer` | `remediation.draft` | applying a change |

`exception-approver` appeared in this table with no grant anywhere in `watchtower/agents.py`. Default-deny means they may write nothing, so the rows claiming otherwise are gone: an intended agent is not a declared one, and this column is generated from the code rather than written beside it.

## Architecture

| Topic | Carries |
|---|---|
| `sec.intake` | everything arriving from outside |
| `sec.tasks` | work for the agent workers; group size is set by VRAM, not partitions |
| `sec.events` | the audit trail, and what the projector and SSE stream read |
| `sec.approvals` | an agent needs a person; resumes a checkpointed graph |
| `sec.dlq` | a consumer gave up; a human looks at it |

| Redis key | Purpose |
|---|---|
| `lock:host:{id}` | one scan per host; a second scan is not twice as good |
| `cache:nvd:{cve}` | the advisory feed is refetched by every worker otherwise |
| `idem:scan:{host}:{feed_version}` | a feed refresh re-screens the estate |
| `live:posture` | the board's counters |

**Postgres:** `assets, packages, feeds, advisories, findings, remediations, exceptions, events`.

**UI, designed and not built** (what ships is the shared operator console at `/`, see [`../README.md`](../README.md)): Textual TUI for the box you are logged into, plus a read-only web board for everything else.

## Real data

This machine and any host you own, plus the public NVD feed and the distribution security trackers. **Scope is a file, and the scanner cannot run outside it** — that is enforced in code, not in a README.

## The deterministic core

`src/watchtower/domain.py` decides whether an installed version is actually vulnerable, and whether a host is in scope at all. It is here rather than in a prompt because it is
arithmetic, matching or a rule — not language work. The model's job is to write the
sentence around the answer, never to produce the answer.

```
PYTHONPATH=src python -m pytest -q
```

## Running it

```bash
cd 11_watchtower
python -m pytest -q                      # 35 passed
PYTHONPATH="src;../platform/src" python -m watchtower.app    # console on http://127.0.0.1:8000
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

- **It does not scan anything outside its scope file.** Out-of-scope targets are refused, not warned about.
- **It does not exploit.** No payload, no proof-of-concept execution. It reports what is present and reachable.
- **It does not patch.** Remediations are drafted; a person applies them.
- **It does not trust a version string alone.** That is the finding.
- **It is not a pentest tool.** It is an inventory-and-advisory reconciler for estates you own.

## Input / Output

Captured from a real run of this product — `scripts/capture.py` submits the payload below
through the HTTP surface, drains the queue, and approves. Every figure here came off a
machine.

**In** — `POST /intake`, keys: `advisories`, `claims`, `host`, `issued_receipts`, `packages`, `scope`

Published to `sec.tasks`; the call returns `202 {"status": "pending"}` with queue lag
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
| Result keys | `advisories`, `applied`, `branch_status`, `branches`, `branches_failed`, `claims`, `claims_checked`, `claims_source`, `draft`, `drop_rate`, `dropped_claims`, `host`, `issued_receipts`, `kept_claims`, `model`, `out_of_scope`, `packages`, `receipts_source`, `remediation.draft`, `scope`, `summary`, `summary_subject`, `vulnerable` |

**The early exit**, on a payload that trips `refused`:

| | |
|---|---|
| Status | `done` |
| Nodes visited | `triage` → `exit` |
| Model calls | **0** |

That last row is the one worth keeping. The cheap refusal costs nothing at all — no
gather, no generation — which is the whole reason it sits before the fan-out.
