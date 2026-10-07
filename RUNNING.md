# Running the eleven tools

*Paths below refer to `projects/NN_name/` inside this repository.*

**Written for: you, at this machine.** Which of these need a UI, which run on a local
server, and what each one costs to start.

Verified 2026-10-07. Every command below was run on this PC.

The counts in the table below - "37 repos", "75 licence files" - describe a folder
of live checkouts on this machine and move with it; the auditor reports 81 today. They
are there to say what the UI is for, not as measurements.

---

## The short answer

**All eleven ship a `ui/`. Three run from the standard library with nothing to
install; four need `npm install`; four need a Python UI framework from their own `ui`
extra.** Every project's CLI is complete without its UI.

The middle number used to be seven, counted as "eleven minus the four with a
`package.json`" - which put `02_test-smith` (nicegui), `08_csv-analyst` (marimo),
`09_log-detective` (panel) and `11_study-tutor` (reflex) in the "nothing to install"
column, each of them listed four lines down in this file's own table as
`uv run --extra ui …`. A split into two is the wrong shape: "needs npm" and "needs
nothing" are not the only options, and the test guarding the sentence classified by
`package.json` alone and then closed the arithmetic with `stdlib + npm == total`,
which is how the subtraction defined itself.

This said "nine of eleven need no UI at all", then "three have a UI that earns its
place", then "four need npm" - sixteen across eleven projects, while
`ls -d projects/*/ui | wc -l` is 11 with four `package.json` files among them. The
judgement underneath still holds: for most of these a browser adds nothing to a command
that prints an answer. That is a different statement from a count and it was written as
one.

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
# From the repository root. The directories are numbered, so a loop over bare
# names fails on the first `cd` - which is what this block used to do, under a
# line saying every command here was run on this PC.
python scripts/test_all.py              # all 33 suites, one process each

# Or the eleven tools alone:
for d in projects/*/; do
  echo "== $d"; (cd "$d" && uv run pytest -q)
done
```

Each project is standalone — its own pyproject, its own tests, no shared imports. The
loop above is the only thing tying them together.

## Honest note on ports

Every server binds `127.0.0.1` only. Three of them (`db-surgeon`, `migration-pilot`,
`review-bot`) accept a filesystem path or SQL in a request and act on it, which is safe
on localhost and would be a serious hole exposed. None of them should be bound to `0.0.0.0`
without authentication in front.
