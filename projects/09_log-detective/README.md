<h1 align="center">log-detective</h1>
<p align="center"><i>Extract log templates, and report what the extraction destroyed</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-51-success" alt="tests">
  <img src="https://img.shields.io/badge/scored%20log%20lines-973-orange" alt="lines">
</p>

---

## Results

**Going from 1.1x to 3.7x compression destroyed 655 of roughly 1,000 distinct messages.**

Template extraction is the standard first move in log analysis, and the number everyone
quotes is the compression ratio. That ratio is bought by deciding two lines are the same
event. Measured on 1,005 real log lines captured from this machine, 973 of which are
non-blank and therefore scored, at every similarity threshold:

```
1,005 lines read, 973 scored (32 blank); every ratio below is over the scored count

 thresh  templates  compression  merged  distinct lost  singletons
    0.9        921         1.1x       0              0         908
    0.8        822         1.2x       6             99         804
    0.7        266         3.7x     104            655         150
    0.6        224         4.3x     108            697         105
    0.5        104         9.4x      22            817          72
    0.4         90        10.8x      24            831          57
    0.3         71        13.7x      26            850          37

  'distinct lost' counts messages that no longer have a template of
  their own. Compression is bought by deciding two lines are the same.
```

There is a cliff between 0.8 and 0.7. Compression triples, and the number of genuinely
different messages that no longer have a template of their own goes from 99 to 655.

**And the lines that vanish are the rare ones.** Templates seen exactly once fall from
908 to 150 across that same step. The singleton is usually the reason you opened the log.

So every template here carries the set of distinct raw messages folded into it, and the
loss is printed next to the compression rather than instead of it.

## Not the same as `incident-copilot`

That repository already does Drain-style extraction and groups the result into incidents
with a ranked suspect change. It answers *"what happened?"*

This one answers *"what did the grouping throw away?"* — the compression/loss trade, the
merged-message list, and which rare templates survive at which threshold. They share an
algorithm and nothing else.

## Input / Output

**In:** one or more `.log` files, or a folder of them.

**Out:** templates with their frequencies, the merged ones with their original messages,
and the compression-versus-loss table above.

```
$ log-detective cost data/                    # the table
$ log-detective templates data/ -v            # patterns, and what each merged
$ log-detective rare data/ --threshold 0.7    # the lines that happened once
$ uv run --extra ui panel serve ui/app.py --show
```

## The corpus is real

1,005 lines captured from this machine, not generated:

- `pytest -v` across 15 zero-dependency repositories in the portfolio
- `git log` across three labs
- `python -X importtime` output

Highly repetitive, structurally uniform, heavy on numbers and paths — the shape
template extraction exists for, which is why it compresses so well and loses so much.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. The extractor is Drain's idea — bucket by
token count, compare by positional similarity, merge by wildcarding disagreements —
implemented directly, because the interesting part is the loss accounting bolted onto it
and `drain3` does not expose that. `panel` is an optional extra used only by the
dashboard.

## Scope

- **No parse tree.** Real Drain uses a fixed-depth prefix tree for speed. This compares
  against every candidate in the length bucket, which is fine for thousands of lines and
  wrong for millions.
- **It cannot tell you the right threshold.** It shows what each one costs. Whether 655
  lost distinctions is acceptable depends on what you are looking for.
- **"Distinct messages" means distinct after masking.** Two lines differing only in a
  timestamp count as one, deliberately — otherwise every line is unique and the metric
  says nothing.
- **No time-series, no anomaly detection, no incident grouping.** Those live in
  `incident-copilot`.
- **Masks are patterns, not semantics.** A version string like `1.2.3` is not recognised,
  and a hex-looking word is called a hash.

## Run it

```bash
uv run pytest -q                    # 51 tests
uv run log-detective cost data/
uv run --extra ui panel serve ui/app.py --show
```

## Layout

```
src/detective/
    templates.py  masking, Drain-style grouping, and the loss accounting
    cli.py        argparse
data/             1,005 real log lines captured from this machine
ui/app.py         Panel dashboard (optional extra)
tests/test_templates.py   35 tests
```
