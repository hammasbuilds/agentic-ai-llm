<h1 align="center">repo-cartographer</h1>
<p align="center"><i>Map an unfamiliar Python codebase from its AST - no embeddings, no model, no dependencies</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-53%20%2B%2013%20skipped-success" alt="tests">
  <img src="https://img.shields.io/badge/median%20resolution-81%25-orange" alt="resolution">
  <img src="https://img.shields.io/badge/pooled%20resolution-75%25-orange" alt="pooled">
</p>

---

## Results

**A plain `ast` walk binds 81% of a repository's internal calls to their definitions
(median across 78 real checkouts, ~1,800 modules, ~350,000 lines) - and 75% when every
call site in all of them is pooled into one fraction. No embeddings, no model, no index.**

The usual approach to "explain this codebase" is to embed every chunk and retrieve by
similarity. For structural questions - *what calls this, what breaks if I change it, where
does execution start* - that is the wrong tool. Similarity cannot tell a definition from a
mention. Symbol resolution can, and it is exact.

Three of the four repositories below 90% are genuinely hard cases, and the fourth was a bug
in this tool. Both are reported.

## Input / Output

**In:** a path to a Python repository.

**Out:**

```
$ cartographer map ~/code/rag-forge

==============================================================================
  rag-forge  -  34 modules, 128 definitions, 2,071 lines
==============================================================================

  CALL RESOLUTION
    133 of 159 repo-internal calls resolved  (84%)
    624 call sites in total; the rest are builtins,
    the standard library, or methods on third-party objects.

  LOAD-BEARING MODULES  (PageRank over internal imports)
    0.1609  ragforge.types
              src/ragforge/types.py  -  47 lines, imported by 11
    0.1295  ragforge.config
              src/ragforge/config.py  -  53 lines, imported by 11
    0.0391  ragforge.store
              src/ragforge/store/__init__.py  -  27 lines, imported by 6

  MOST-CALLED DEFINITIONS
      12 callers  ragforge.config.get_settings  (src/ragforge/config.py:51)
      10 callers  ragforge.store.get_store  (src/ragforge/store/__init__.py:12)
       9 callers  ragforge.db.connection  (src/ragforge/db.py:37)

  ENTRY POINTS  (public, nothing in the repo calls them)
    ragforge.cli.ask  (src/ragforge/cli.py:25)  - Ask a question against the index.
    ragforge.api.main.ask  (src/ragforge/api/main.py:57)
==============================================================================
```

Also:

```
$ cartographer impact ~/code/rag-forge get_settings   # blast radius of a change
$ cartographer compare ~/code                         # every checkout under a folder
$ cartographer map <repo> --json -o map.json             # for the UI
```

## Measured across 78 repositories

Every checkout in one folder, not a chosen subset — `cartographer compare <folder>`, whose
last three lines are this table. Measured 2026-10-06, and it is a snapshot: these are live
repositories and committing to any of them moves the row it is in. The five maps under
`ui/public/data` each record the revision they were taken at for the same reason.

**The rates are the measurement; the absolute counts are not.** An independent review
re-ran the command the day after this was dated and found every rate unchanged and every
raw count moved — 1,740 modules to 1,768, 339,739 lines to 349,104, 32,527 call sites to
33,110, 26 skipped checkouts to 27 — because several of those repositories are worked on
daily. A table printed as verbatim command output was wrong in four of eight rows within
a day of being recorded, and nothing here checked it.

The line counter has also changed since those two runs. It was
`source.count("\n") + 1`, which counts an empty final line in every file that ends in
a newline, so both totals were high by roughly one per module - about 1,740 of the
339,739. It is `len(source.splitlines())` now, which is what `wc -l` reports, and
`tests/test_parse.py` asserts it over six shapes of file including an empty one. The
figures above are left as they were measured; the share they are quoted for is
unaffected, because a line count appears in no rate on this page.

So the counts below are given as the order of magnitude they are stable at, and the
measurement is the share. What a reader wants from this table is whether an AST resolver
binds most of a repository's internal calls, and that answer has not moved.

| | | |
|---|---|---|
| Repositories measured | 78 | stable |
| Modules | ~1,800 | moves daily |
| Lines | ~350,000 | moves daily |
| **Median repo-call resolution** | **81%** | the measurement |
| **Pooled over ~33,000 internal call sites** | **75%** | the measurement |
| Median over *all* call sites, for contrast | 21% | the measurement |
| At or above 90% | 18 of 78 | stable |
| With fewer than 50 internal call sites | 9 of 78 | stable |
| Parse failures | 1 | stable |
| Checkouts holding no Python, skipped | 26–27 | moves |

The median and the pooled rate differ by six points, and the row `n` in the table above
says why: the median weighs a repository with nine internal call sites the same as one
with over a thousand. `vision-language-lab` scores 100% on nine, `visual-analytics` 67% on three.
Nine of the 78 have fewer than fifty, which is where a percentage is a coin flip with a
decimal point. The pooled fraction is the one to quote for the resolver; the median is the
one to quote for a repository picked at random, and both are printed because neither
answers the other's question.

This said **99% across 29 repositories** until two things changed, and both moved it down.

The denominator was wrong in the direction that flatters: every `x.method()` on a variable
whose type an AST cannot infer went to *out of scope*, which removes it from the
denominator rather than counting it as unresolved — and in code written with classes those
are the calls. They are now in scope when this repository defines a method of that name.

And 29 was a subset. Over every checkout in the folder, including the ones that are mostly
notebooks, scripts or someone else's vendored code, the median is 81%. The lowest:
`contract-reader` (29%), `urdu-desk` (32%), `_fifteen_build` (38%), `router-14b` (40%), `model-serving-platform` (43%), `minimal-diff` (46%).

A repository of two scripts with almost no internal calls swings several points on one
miss, which is why the median is quoted rather than the mean — and why the count at or
above 90% is beside it. `compare` used to print that rate with no `n` beside it, so those
repositories were invisible: 100% over nine call sites and 100% over nine thousand were
the same line of output.

## The denominator matters more than the resolver

The first version of this tool reported **12%** resolution on `mcp-lab` and **7%** on
`machine-learning`. Both numbers were meaningless. Most call sites in any Python file are
`len`, `print`, `path.resolve()` or a method on a third-party object - none of which could
*ever* bind to a definition in the repository being mapped.

Counting them in the denominator makes every codebase look unmappable:

| Repository | All call sites | Repo-internal calls only |
|---|---|---|
| machine-learning | 8% | **81%** |
| mcp-lab | 11% | **75%** |
| rag-forge | 21% | **84%** |
| credit-risk-engine | 21% | **76%** |
| langchain-lab | 38% | **93%** |

This is the same mistake `langchain-lab` project 01 found in extraction scoring, where the
standard metric dropped failed extractions from the denominator and made
grammar-constrained decoding look 19 points *worse* than plain prompting when it was three
times better. Same shape, different field: **the resolver was never the problem, the
denominator was.**

Both numbers are reported. `resolution_rate` is every call site; `repo_resolution_rate` is
the honest one.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. The parser, the call resolver, the PageRank
implementation, the scope handling and the CLI are all standard library. `pytest` and
`ruff` are development-only.

This is not purism. tree-sitter was tried first and beaten by `ast` on the actual task, and
an embedding index was never built because similarity search cannot answer the structural
questions this tool exists for.

## Scope

- **Python only.** No JavaScript, Go or Rust. The `ast` module is the reason it works and
  the reason it does not generalise.
- **No type inference.** `conn.execute(...)` is unresolvable without knowing what `conn` is.
  These are counted as out of scope, not guessed at.
- **No dynamic dispatch.** Registry dictionaries, `getattr`, plugin loading and
  argparse-bound callables are invisible. This is why `computer-vision` sits at 60%.
- **Does not run, import, or install the code it maps.** Parsing only, so mapping a
  repository is safe even when its dependencies are not installed.
- **Does not rank by quality.** PageRank finds what is depended upon, which is not the same
  as what is good.
- **The explanation layer is optional and not the point.** The map is produced with no model
  at all; a model only turns it into prose.

## Run it

```bash
uv run pytest -q                      # 53 passed, 13 skipped
uv run cartographer map <repo>
uv run cartographer compare <folder>  # every checkout under it
```

The 13 skips need a folder of real git checkouts, which `REPOS_ROOT` names; it defaults
to the folder this repository sits in, so all 49 run on the machine this was written on.
The figure above is a fresh clone's. One of those tests used to *fail* rather than skip
there - it asserted that at least one shipped map was still at the revision it records,
which cannot be true when there is no checkout to compare against - so the suite was red
in exactly the configuration CI runs in, with a message telling the reader to regenerate
artifacts that were current.

## Layout

```
src/cartographer/
    parse.py    file walk, AST walk, symbols, imports, call sites
    graph.py    call resolution, the honest denominator, PageRank
    report.py   the four questions a newcomer asks
    cli.py      argparse, because the core has no dependencies
tests/
    test_parse.py   18 tests
    test_graph.py   14 tests
```
