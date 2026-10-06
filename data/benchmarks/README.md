# Committed benchmark slices

The columns these apps read, sliced out of four public datasets and committed. 2.8 MB,
beside the 460 KB of GitHub tree listings in `../trees` which are committed for the same
reason: so the measurements this repository says are reproducible offline are.

| File | From | Columns kept | Read by |
|---|---|---|---|
| `swebench_lite_test.parquet` | `princeton-nlp/SWE-bench_Lite` test, 300 rows | `instance_id`, `repo`, `base_commit`, `problem_statement`, `hints_text`, `patch` | `apps/_engine/localize_eval`, app 01 |
| `devign_test.parquet` | `google/code_x_glue_cc_defect_detection` test, 2,732 rows | `func`, `target` | app 03 |
| `mbpp.jsonl` | `Muennighoff/mbpp`, 972 problems | all (already small) | apps 02, 04–10 |
| `sanitized-mbpp.json` | `Muennighoff/mbpp`, 413 problems | all | app 02 |

`apps/_engine/hf_cache.resolve()` prefers a real Hugging Face cache and falls back to
these, because a machine with the full download should use it — the slices carry only the
columns read today and a later measurement may want another one.

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
(300 / 2,732 / 972 / 413) and the always-SAFE baseline app 03's README quotes, so a bad
re-slice fails rather than quietly changing a number.

## Licences

SWE-bench Lite is MIT (Princeton NLP). CodeXGLUE defect detection is MIT (Microsoft),
derived from the Devign dataset. MBPP is CC-BY-4.0 (Google Research). All four are
redistributed here under those terms, unmodified except for column selection.
