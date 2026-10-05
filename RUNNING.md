# Running the eleven tools

*Paths below refer to `projects/NN_name/` inside this repository.*

**Written for: you, at this machine.** Which of these need a UI, which run on a local
server, and what each one costs to start.

Verified 2026-09-17. Every command below was run on this PC.

---

## The short answer

**Nine of eleven need no UI at all.** They answer a question and print it; a browser adds
nothing. Three have a UI that earns its place, and all three run from the standard
library with **nothing to install**.

Four have a UI written against a framework that needs `npm install` first. Those are
optional, and the CLI is complete without them.

## Start immediately — no install, no npm

These run the moment you open a terminal. Each serves a page on localhost.

| Tool | Command | Port | Why a UI helps |
|---|---|---|---|
| `release-captain` | `python ui/serve.py` | 8090 | Pick a repo, see the go/no-go and the riskiest commits |
| `compliance-auditor` | `python ui/serve.py` | 8100 | 37 repos × 10 controls is a grid, not a list |
| `contract-reader` | `python ui/serve.py` | 8115 | 75 licence files you want to sort and scan |

All three are one HTML file plus `http.server`. Alpine, Lit and plain JS respectively,
loaded from a CDN or inlined — no build step.

## CLI only — a UI would be decoration

These print an answer. There is nothing to click.

| Tool | The one command worth running |
|---|---|
| `repo-cartographer` | `cartographer compare ~/code` |
| `test-smith` | `testsmith run <repo> --limit 40` |
| `csv-analyst` | `csv-analyst report <csv> --limit 100000` |
| `db-surgeon` | `db-surgeon corpus` |
| `migration-pilot` | `migration-pilot scan ~/code` |
| `review-bot` | `review-bot scan <path> --show-retracted` |
| `study-tutor` | `study-tutor compare` |
| `log-detective` | `log-detective cost data/` |

`repo-cartographer` and `csv-analyst` also emit JSON (`--json`) if you want to feed
something else.

## Needs `npm install` first — optional

Written, committed, never installed, because the link here has been saturated all
session. The CLI in each is complete without them.

| Tool | UI | To start |
|---|---|---|
| `repo-cartographer` | Astro | `cd ui && npm install && npm run dev` |
| `db-surgeon` | SolidJS + Vite | `python ui/server.py` then `cd ui && npm install && npm run dev` |
| `migration-pilot` | Vue 3 + Vite | same shape, API on 8105 |
| `review-bot` | Remix | same shape, API on 8110 |

Each Python API server is standard library and starts on its own; only the front end
needs npm.

## Needs a Python extra — one `uv sync` away

| Tool | UI | To start |
|---|---|---|
| `test-smith` | NiceGUI | `uv run --extra ui python ui/app.py` |
| `csv-analyst` | Marimo | `uv run --extra ui marimo edit ui/notebook.py` |
| `study-tutor` | Reflex | `uv run --extra ui reflex run` |
| `log-detective` | Panel | `uv run --extra ui panel serve ui/app.py --show` |

These pull one package each. The measurement never imports it.

---

## What I would actually do

**Run the three zero-install servers.** They are the ones where seeing beats reading, and
they cost nothing.

**Leave the npm four alone** unless you want the framework variety on the CV. They were
built partly to prove no two projects share a frontend, which is a portfolio argument
rather than a usefulness one, and the README of each says the CLI is the real interface.

**Install the Python extras only for `csv-analyst`.** A Marimo notebook over a CSV
profile is genuinely nicer than terminal output, and it is one dependency.

## Testing everything at once

```bash
for r in repo-cartographer test-smith release-captain csv-analyst db-surgeon \
         compliance-auditor migration-pilot review-bot study-tutor \
         log-detective contract-reader; do
  echo "== $r"; (cd "$r" && uv run pytest -q)
done
```

Each project is standalone — its own pyproject, its own tests, no shared imports. The
loop above is the only thing tying them together.

## Honest note on ports

Every server binds `127.0.0.1` only. Three of them (`db-surgeon`, `migration-pilot`,
`review-bot`) accept a filesystem path or SQL in a request and act on it, which is safe
on localhost and would be a serious hole exposed. None of them should be bound to `0.0.0.0`
without authentication in front.
