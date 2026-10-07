<h1 align="center">contract-reader</h1>
<p align="center"><i>Read a licence, and cite the character span behind every claim</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/real%20licences-94-orange" alt="licences">
</p>

---

## Results

**A keyword classifier reads the Python licence as GPL, because the Python licence names
the GPL.**

`typing_extensions` ships the PSF licence. Buried in it is a choice-of-law clause:

> Notwithstanding the foregoing, with regard to derivative works based on Python 1.6.1
> that incorporate non-separable material that was **previously distributed under the GNU
> General Public License (GPL)**, the law of the Commonwealth of Virginia shall govern
> this License Agreement.

The string "GNU General Public License" is right there. Any tool matching on it flags
copyleft contamination in a portfolio that has none, and somebody spends an afternoon on
it.

So no phrase becomes a finding until the sentence around it has been checked, and the
span is reported so the reader can disagree:

```
  family: PSF
    because chars 1204-1261 say "this license agreement is between the
    python software foundation"
```

Across **94 real licence files** in this portfolio, read on 2026-10-05:

| family | files |
|---|---|
| MIT | 75 |
| BSD | 14 |
| Apache-2.0 | 3 |
| CC | 1 |
| unknown | 1 |

**One file in ninety-four is unidentifiable**, and it is honestly so: 51 bytes reading
`Copyright 2019 Kenneth Reitz. All rights reserved.` with no grant of any kind. A grant
is what makes a licence, so "obligations unknown" is the right answer for it.

It used to be 26 of 198, and each of those 26 was reported as a conflict. Three causes,
none of them the conflict rule:

- **Every Creative Commons file read as unknown**, including this author's own
  `llm-agentic-datasets`. The CC licences open with *"Creative Commons Corporation …
  **is not a** law firm and **does not** provide legal services"* — and `is not a` and
  `does not` are context disqualifiers, written to stop the PSF licence being read as
  GPL because it names the GPL in a compatibility clause. Only the first occurrence of a
  name was examined, so the disclaimer decided. Every occurrence is now considered.
- **Documentation pages were read as licences.** Sphinx and MkDocs projects ship
  `docs/license.rst` saying "see LICENSE in the root"; twelve of those were read, failed
  to identify, and were each reported as a conflict.
- **Virtualenvs were surveyed.** The skip list named `.venv` and `.venvs`, so
  `.venv-check` was walked and the survey filled with third-party packages. A
  virtualenv is now detected by its `pyvenv.cfg`, which is what makes one.

That is a tool whose first duty is not to cry wolf being wrong about 13% of what it read.
The three causes are pinned as fixtures in
[`tests/fixtures/`](tests/fixtures), not against this disk — an earlier version of this
section described two MPL-2.0 packages under `gan-diffusion-projects/pylibs/`, and that
tree is no longer on the machine, so the finding could not be checked at all. **Nothing
in the tree is GPL.**

## Input / Output

**In:** a licence file, or a folder to search.

**Out:** the licence family, its obligations, and the character span behind each one.

```
$ contract-reader read mcp-lab/LICENSE

  family: MIT
    because chars 49-93 say "permission is hereby granted, free of charge"

  OBLIGATIONS  (each with the span that proves it)
    [low   ] attribution
             You must keep the copyright notice
             chars 487-509 in (whole document): "above copyright notice"
    [low   ] no-warranty
             Supplied with no warranty
             chars 645-673: "without warranty of any kind"
```

```
$ contract-reader survey ~/code --project MIT
$ contract-reader obligations          # what it looks for, to argue with
$ python ui/serve.py                   # http://127.0.0.1:8115
```

## Does it need a UI? No — but it has one, and it costs nothing

The CLI is the real interface. The build plan called for React + Vite here, and that
would have meant `npm install` and a bundler to render three tables. **The UI is instead
one HTML file served by `http.server`** — `python ui/serve.py` and it is up, on a clone,
with nothing installed.

The UI earns its place for one thing only: a 75-file survey is a table you want to sort
and scan, not read in a terminal. Everything else is better in the CLI.

## Two rules, and the second is the whole project

1. **A claim is produced only by a phrase found in the document**, and the offsets are
   reported. A test asserts that for every finding, `source[start:end]` equals the phrase
   claimed — an ungrounded claim cannot survive the suite.
2. **A phrase inside a disclaiming sentence does not count.** `compatible with`,
   `is not a`, `unlike`, `previously distributed under`, `notwithstanding the
   foregoing` — a match inside any of these is recorded as rejected, with the sentence,
   rather than becoming a finding.

Rule 1 is inherited from `rag-forge`, where a quote that could not be located in the
source was treated as a hallucination signal. Rule 2 is what this corpus added.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. Segmentation, phrase location and the
context check are `re` and string offsets. The UI is one HTML file and `http.server`.
`docling` was the planned dependency for PDF contracts; the corpus here is plain text, so
it would have added forty megabytes to parse nothing.

## Scope

- **This is not legal advice**, and the compatibility check reports only the two cases
  that are not arguable: strong copyleft inside a permissive project, and a licence it
  could not identify.
- **Phrase matching, not comprehension.** A licence that states an obligation in words
  this does not know will be missed silently, and there is no way for the tool to tell
  you that happened.
- **Plain text only.** No PDF, no DOCX.
- **English only.**
- **It reads licences, not contracts.** The clause segmentation handles numbered sections
  and ALL-CAPS headings; a commercial agreement with nested definitions and schedules
  would defeat it.
- **`unknown` means unknown.** One file in this corpus is unidentified and the tool says
  so rather than guessing the closest match — the same one the Results section counts.
  This said "four", which is the number of keyword matches the reader *rejected* as too
  weak to name a family; those are a different quantity and the two sat eighty lines
  apart contradicting each other.

## Run it

```bash
uv run pytest -q                                   # 46 tests
uv run contract-reader survey ~/code
uv run contract-reader read <path/to/LICENSE> -v
uv run python ui/serve.py                          # :8115, nothing to install
```

## Layout

```
src/contractreader/
    segment.py      clause splitting and whitespace-tolerant phrase location
    obligations.py  families, obligations, the context check, compatibility
    cli.py          argparse
ui/                 one HTML file served by http.server
tests/test_reading.py     34 tests  the reader, and the README's own numbers
tests/test_cli_inputs.py  12 tests  a .csv, a PNG and an empty file are not licences
```
