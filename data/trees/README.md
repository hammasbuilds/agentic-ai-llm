# Committed repository file listings

Path lists — filenames only, no file contents — for the twelve repositories SWE-bench
Lite draws its instances from. 460 KB gzipped, beside the 2.8 MB of dataset slices in
[`../benchmarks`](../benchmarks), committed for the same reason: so the retrieval
measurements this repository publishes reproduce offline.

A retriever here ranks candidate *files* for a bug report. It needs to know which files
exist in a repository at the commit the issue was filed against, and nothing else — so
what is committed is the output of `git ls-tree -r --name-only`, and never a line of
anyone's source.

| Repository | Listings | Paths | Upstream licence |
|---|---|---|---|
| `astropy/astropy` | 1 | 1,876 | BSD-3-Clause |
| `django/django` | 3 | 18,625 | BSD-3-Clause |
| `matplotlib/matplotlib` | 2 | 8,768 | PSF-based (matplotlib licence) |
| `mwaskom/seaborn` | 1 | 260 | BSD-3-Clause |
| `pallets/flask` | 1 | 235 | BSD-3-Clause |
| `psf/requests` | 1 | 121 | Apache-2.0 |
| `pydata/xarray` | 1 | 234 | Apache-2.0 |
| `pylint-dev/pylint` | 2 | 5,451 | GPL-2.0-or-later |
| `pytest-dev/pytest` | 2 | 1,111 | MIT |
| `scikit-learn/scikit-learn` | 9 | 11,494 | BSD-3-Clause |
| `sphinx-doc/sphinx` | 1 | 1,591 | BSD-2-Clause |
| `sympy/sympy` | 10 | 17,129 | BSD-3-Clause |

34 listings, 66,895 paths. Several repositories appear more than once because an
instance is scored against the tree **at its own base commit**: `scikit-learn` has nine
because nine of the instances used here sit at nine different commits, and resolving
them all against one listing would credit a retriever for naming a file that did not
exist yet.

## Licences

A file listing is a set of names, not the work. It is committed here as a factual record
of what each repository contained at a given commit, and the table above names each
project's licence so a reader can see which terms the work those names belong to is
under. No source, documentation or other copyrightable content from any of them is in
this directory. Where a project's own licence is the stricter of the set — `pylint` is
GPL-2.0-or-later — that applies to its source, which is not here.

## File names and shape

`<owner>__<repo>.json.gz` is a listing of the default branch.
`at__<owner>__<repo>__<commit12>.json.gz` is a listing at that commit, which is the form
every scored instance uses. Each file holds one object:

```json
{"repo": "django/django", "ref": "<full sha or branch>", "how": "at_commit", "paths": ["..."]}
```

`how` records where the listing came from: `at_commit` (22) and `recursive` (9) are the
GitHub trees API, `walked` (3) is a local checkout. It is kept because the three are not
interchangeable — the API truncates a very large tree and says so, a walk does not.

## Regenerating

`scripts/fetch_trees.py`, and nothing else:

```bash
python scripts/fetch_trees.py --repo django/django
python scripts/fetch_trees.py --repo astropy/astropy --commit 1e8a5b833d1b
python scripts/fetch_trees.py --missing      # every listing a scored instance needs and lacks
```

It writes into this directory and records `how`, so a listing is never silently
replaced by one obtained a different way. `--missing` reads the committed benchmark
slice, so it says what is absent without fetching anything first.

This section used to say there was no script: that `apps/_engine/trees.py` wrote a
listing "the first time one is asked for and not already here", and that running
`python -m apps._engine.localize_eval` against an instance whose tree was missing
would fetch and commit it. `fetch` and `fetch_at_commit` had no caller anywhere in the
repository — that is how a check resolving references through the import graph found
them — so nothing fetched on demand, and the command named here would have reported
the instance as unlistable instead.

Fetching is deliberately not on the evaluation path. It needs the GitHub API, and a
measurement that reaches the network when a file is missing is a measurement whose
result depends on whether the network was up; the listings are committed so that it
cannot. A listing is refreshed on purpose, by running the script.

`tests/test_hermetic.py` asserts these load with `HF_HOME` and `HF_HUB_CACHE` pointed at
an empty directory, and `tests/test_dataset_provenance.py` asserts every repository with
a listing here appears in the table above, with the counts this page prints.
