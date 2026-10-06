<h1 align="center">migration-pilot</h1>
<p align="center"><i>Modernise Python where the rewrite is provably equivalent, and refuse where it would change meaning</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-28-success" alt="tests">
  <img src="https://img.shields.io/badge/files%20scanned-3%2C028-orange" alt="files">
</p>

---

## Results

**The documented fix for a deprecation warning can break your program, and the diff will
not show it.**

Python 3.12 deprecates `datetime.utcnow()`. The documentation says to write
`datetime.now(timezone.utc)`. That is one token, it looks like a rename, and it changes a
**naive** datetime into an **aware** one. Every comparison against a naive datetime
elsewhere then raises at runtime - in a function the diff never touched.

```
$ python scripts/prove_utcnow.py

A stored naive timestamp: 2026-09-17 12:00:00 (tzinfo=None)

before the fix:
  session_expired_old(stored) -> False

after applying the documented replacement:
  TypeError: can't subtract offset-naive and offset-aware datetimes
```

So this tool classifies every rule before it will run it:

| | |
|---|---|
| **mechanical** | provably equivalent. `typing.List[int]` and `list[int]` are the same type. Applied automatically. |
| **behavioural** | what the deprecation notice tells you to write, and not the same program. Reported, never applied. |

## Measured

Every Python file under one folder of checkouts — the portfolio plus whatever vendored
code the repositories in it carry:

```
$ migration-pilot scan <folder> --limit 0

  files scanned    : 3,028
  files with edits : 10
  parse errors     : 2
      classical-computer-vision/projects/40_multiframe_super_resolution/run.py:
          line 281: unterminated f-string literal
      worktree-fleet/targets/.fleet/work/more-itertools/.../more.py:
          line 3624: expected an indented block after 'while' statement
  mechanical       : 18   (provably equivalent, safe to apply)
  behavioural      : 12   (changes meaning, never auto-applied)
      mechanical   pep585-generics                18
      behavioural  utcnow-deprecated              11
      behavioural  naive-now                      1
```

`files scanned` is new, and so are the named parse errors. This README quoted
`files scanned = 1,675` in a block the command did not print: `scan` reported edits and
counted parse errors and never counted the files it had read, so the denominator under
"19 edits" had no source in the tool. The second of the two unparseable files is a
deliberately-mutated copy in another project's mutation-testing work area; the first is
real, and is the same file `repo-cartographer` reports as the one module in the folder
that does not parse.

### The ratio this section used to lead with has flipped

It said **"More of what a modernisation scan finds changes behaviour than does not"**, on
7 mechanical against 12 behavioural. Re-run over the folder it is **18 mechanical against
12 behavioural**, and the claim is now false in the direction that matters: most of what
the scan finds *is* safe to apply.

Nothing about the tool changed to cause that. `pep585-generics` went from 7 to 18 because
there is more `typing.List[...]` on this disk than there was, and the two counts are so
small that a handful of files decides the comparison. The previous version of this section
said so itself — *"19 edits across 1,675 files is a small sample, and it is small because
the corpus is already modern. The ratio is suggestive, not established."* That caveat was
correct, and the headline above it should not have been stated as a finding.

What does not depend on sample size is the distinction the tool is built on: that
`utcnow-deprecated` has a documented fix which changes the program, and that
`pep585-generics` does not. Eleven of the twelve behavioural edits are that one rule, and
`prove_utcnow.py` demonstrates the breakage rather than asserting it.

## Input / Output

**In:** a Python file, or a folder of them.

**Out:** every applicable edit, split into the ones that will be applied and the ones
that never will, each with the source text it would replace.

```
$ migration-pilot scan ~/code --verbose

pallets__flask-4045\src\flask\sessions.py
  [REVIEW] line   273  utcnow-deprecated
           datetime.utcnow()  ->  datetime.now(timezone.utc)
           utcnow() returns a NAIVE datetime; now(timezone.utc) returns an AWARE one.
           Comparing the two raises TypeError, so this is a semantic change, not a
           rename. Requires `from datetime import timezone`.

  files with edits : 12
  mechanical       : 7    (provably equivalent, safe to apply)
  behavioural      : 12   (changes meaning, never auto-applied)
```

```
$ migration-pilot apply src/            # dry run, prints a diff
$ migration-pilot apply src/ --write    # mechanical edits only, always
$ migration-pilot rules                 # every rule and its classification
$ python ui/server.py                   # API for the Vue UI on :8105
```

## Two guarantees, checked rather than assumed

**The rewrite parses.** An edit producing invalid Python is discarded and reported, never
written.

**Only annotations changed.** For mechanical rules the rewritten module must be
AST-equivalent to the original once annotations are stripped. If a rule ever altered
executable code, the file is left untouched and the rejection says so. There is a test
that sabotages an edit to prove the check fires.

## Edits are text slices, not a reformat

Locating with `ast` and applying with text offsets means a two-line change stays a
two-line diff:

```python
def f(
    a: Optional[str],  # keep this comment
    b: int = 3,
) -> List[int]:
    """Docstring stays."""
    return [1, 2]
```

becomes `a: str | None` and `-> list[int]`, with the comment, the docstring and the odd
spacing in `[1,  2]` untouched. Round-tripping through `ast.unparse` would have been
twenty lines shorter to write and would reformat every file it touched, turning a
reviewable diff into an unreviewable one.

Nested generics need more than one pass - `Dict[str, List[Optional[int]]]` produces
overlapping edits, so the innermost is applied first and the scan repeats until stable.
`--write` runs to a fixed point.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. `ast` locates, `difflib` renders the dry-run
diff, `http.server` serves the API. `ast-grep` was the planned tool and was not needed -
and would not have given the mechanical/behavioural split, which is the part that
matters. Only the Vue front end needs npm.

## Scope

- **Six rules.** This is not `pyupgrade`, which has dozens. The contribution is the
  refusal, not the coverage.
- **It does not add imports.** Applying the `utcnow` fix needs
  `from datetime import timezone`; since that rule is never auto-applied, nothing here
  edits an import block.
- **It does not remove imports left unused.** After rewriting `List[int]` the
  `from typing import List` line is dead, and removing it safely needs whole-module
  reference analysis this does not do.
- **Type comments and stub files are ignored.**
- **The equivalence check only guards mechanical rules**, and only against changes to
  executable code. A mechanical rule that produced a *wrong annotation* would pass it.
- **Behavioural findings are not judgements.** `datetime.now()` with no timezone may be
  exactly right in a local-time application.

## Run it

```bash
uv run pytest -q                        # 28 tests
uv run python scripts/prove_utcnow.py   # the demonstration
uv run migration-pilot scan ~/code
uv run migration-pilot rules
uv run python ui/server.py              # then: cd ui && npm install && npm run dev
```

## Layout

```
src/pilot/
    rules.py    six rules, each classified mechanical or behavioural
    apply.py    text-slice edits, parse check, AST-equivalence check
    cli.py      argparse
scripts/prove_utcnow.py   runnable proof that the documented fix breaks code
ui/                       Vue 3 + Vite, http.server API
tests/test_rules.py       25 tests, mostly asserting what it refuses to do
```
