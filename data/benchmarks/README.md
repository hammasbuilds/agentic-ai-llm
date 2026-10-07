# Committed benchmark slices

The columns these apps read, sliced out of four public datasets and committed. 2.8 MB,
beside the 460 KB of GitHub tree listings in `../trees` which are committed for the same
reason: so the measurements this repository says are reproducible offline are.

| File | From | Columns kept | Read by |
|---|---|---|---|
| `swebench_lite_test.parquet` | `princeton-nlp/SWE-bench_Lite` test, 300 rows | `instance_id`, `repo`, `base_commit`, `problem_statement`, `hints_text`, `patch` | `apps/_engine/localize_eval`, app 01 |
| `devign_test.parquet` | `google/code_x_glue_cc_defect_detection` test, 2,732 rows | `func`, `target` | app 03 |
| `mbpp.jsonl` | `Muennighoff/mbpp`, **974 rows**, 972 usable | all (already small) | apps 02, 04–10 |
| `sanitized-mbpp.json` | `Muennighoff/mbpp`, **427 rows**, 413 usable | all | app 02 |

`apps/_engine/hf_cache.resolve()` prefers a real Hugging Face cache and falls back to
these, because a machine with the full download should use it — the slices carry only the
columns read today and a later measurement may want another one.

### Rows against usable rows

Two of the four numbers above used to be row counts and two were not. `mbpp.jsonl` has
974 lines and `sanitized-mbpp.json` 427 entries; the 972 and 413 printed there were what
survived `load_mbpp`, which skips any row whose tests never call a function it can name
as the entry point — a bare `continue` with no counter. Sixteen rows in all:

| Slice | Rows | Usable | Discarded |
|---|---|---|---|
| `mbpp.jsonl` | 974 | 972 | `mbpp/769`, `mbpp/927` |
| `sanitized-mbpp.json` | 427 | 413 | `mbpp/82`, `mbpp/85`, `mbpp/98`, `mbpp/124`, `mbpp/137`, `mbpp/139`, `mbpp/163`, `mbpp/233`, `mbpp/246`, `mbpp/248`, `mbpp/276`, `mbpp/300`, `mbpp/312`, `mbpp/769` |

Every rate the apps publish is over *usable*, which is the right denominator — there is
nothing to run a reference against in a row with no named entry point. What was wrong was
printing it in a column headed with the other two slices' row counts, in the directory
whose job is making the measurements reproducible, for apps whose stated discipline is
publishing the denominator. App 02 names the one problem whose reference fails its own
tests and accounts for it; these sixteen had already gone, one layer below.

`datasets.mbpp_population(split)` returns all three figures and the ids, so the exclusion
can be argued with. `tests/test_dataset_provenance.py` holds this table to it.

## Why they are here

Without them the suite was not hermetic and nobody could tell, because the same resolver
bug hid it. `HF_HOME` and `HF_HUB_CACHE` were *appended to* `~/.cache/huggingface/hub`
rather than replacing it, in three copies of the logic, so pointing one at an empty
directory did not isolate the suite — every check of whether it ran offline was reading
the real cache.

Run hermetically, the suite gave **11 failures, not skips**: the tests that assert what a
runner does when the model is unreachable hit `FileNotFoundError` first and failed their
`isinstance` check. `datasets` is in neither `pyproject.toml` nor `uv.lock`, so the
download fallback could not fire either, and CI had never executed those files.

`tests/test_hermetic.py` now asserts the override is an override, that exactly one
resolver exists, that each slice loads with the cache pointed at an empty directory, and
that the flagship BM25 figures reproduce from them.

## Regenerating

These are derived files, not hand-edited ones. Re-slice from a full Hugging Face cache:

```bash
python scripts/slice_benchmarks.py        # writes all four, prints each size
```

The column lists above are the contract. `tests/test_hermetic.py` asserts the row counts
(300 / 2,732 / **974** / **427**) *and* the usable counts (972 / 413) as separate
numbers, plus the always-SAFE baseline app 03's README quotes, so a bad re-slice fails
rather than quietly changing a number. It used to assert `len(load_mbpp(...))` under a
sentence promising it asserted row counts, which is how the difference stayed invisible.

## Licences

SWE-bench Lite is MIT (Princeton NLP). CodeXGLUE defect detection is MIT (Microsoft),
derived from the Devign dataset. MBPP is CC-BY-4.0 (Google Research). All four are
redistributed here under those terms, unmodified except for column selection.
