<h1 align="center">log-detective</h1>
<p align="center"><i>Extract log templates, and report what the extraction destroyed</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-60-success" alt="tests">
  <img src="https://img.shields.io/badge/corpus%20measured-2.1M%20lines-blueviolet" alt="corpus">
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

### That cliff is this log's cliff

1,005 lines of one machine's pytest output is enough to show the trade exists and not
enough to say where it falls. `scripts/fetch_logs.py` fetches
[Loghub](https://github.com/logpai/loghub) — nine production systems, 2.1 million lines —
and `scripts/sweep_corpus.py` runs the same sweep over each:

```
  Loghub, 9 systems, first 25,000 lines of each at most.
  'lost' is the share of distinct messages with no template of their own.

  system       scored       0.9      0.8      0.7      0.6      0.5      0.4      0.3
  -----------------------------------------------------------------------------------
  apache        25000     78.6x   316.5x   543.5x   757.6x   543.5x   531.9x   757.6x
                 lost      17%      18%      18%      18%      18%      18%      18%
  hadoop        24899     12.7x    52.0x    86.8x    99.6x   161.7x   197.6x   273.6x
                 lost       9%      15%      15%      16%      16%      16%      16%
  healthapp     25000      1.0x     1.2x     1.5x     1.6x     4.9x     4.9x     4.9x
                 lost       2%      16%      34%      37%      79%      79%      79%
  hpc           25000        --    13.5x   735.3x  6250.0x  8333.3x  8333.3x  8333.3x
                 lost        --     81%      88%      88%      88%      88%      88%
  linux         25000      6.6x    22.2x    50.6x    71.8x    91.2x   156.2x   297.6x
                 lost      34%      45%      47%      48%      48%      49%      49%
  openssh       25000     58.1x  1000.0x  1041.7x  1041.7x   694.4x  1250.0x  1666.7x
                 lost      98%     100%     100%     100%     100%     100%     100%
  openstack     25000      9.2x    43.9x    30.1x    84.2x   925.9x   892.9x  1388.9x
                 lost      64%      72%      71%      74%      75%      75%      75%
  proxifier     21329      3.6x    12.5x   190.4x   561.3x   627.3x   790.0x   888.7x
                 lost      34%      53%      61%      61%      61%      61%      61%
  zookeeper     25000    176.1x   333.3x   396.8x   454.5x   555.6x   694.4x  1087.0x
                 lost       8%       8%       8%       8%       8%       8%       8%
```

**There is no single cliff.** ZooKeeper loses a flat 8% of its distinct messages at every
threshold from 0.9 to 0.3 while compressing six times harder; Apache the same at 18%. For
those two the threshold is nearly free. HealthApp goes from 2% to 79%, and its cliff is
between 0.6 and 0.5, not between 0.8 and 0.7. **Where the cost falls is a property of the
log format, and there is no threshold that is right for all nine.** Run the sweep on your
own logs; that is what the command is for.

**A compression ratio with 100% loss is not a result.** OpenSSH reads 1000x at a
threshold of 0.8 and has lost every distinct message's own template by then — the
templates are general enough to match anything and to tell you nothing. Read the two
columns together or neither.

**The threshold is not a monotonic dial.** On 25,000 lines of the Apache log the template
count goes 33 at 0.6, 46 at 0.5, 47 at 0.4 and 33 at 0.3 — loosening it compressed half
as much again. Clustering is a single greedy pass, so the threshold changes which lines
join which cluster, and a line that would have started its own cluster instead widens an
earlier one until later lines no longer match it. `cost` prints `NOT MONOTONIC` when its
own table bends, because the shape of the table invites the other conclusion.

**One cell does not finish.** Clustering compares every line against every template in
its token-count bucket, so the cost is quadratic in the number of templates: 25,000 lines
of the HPC log take 1.5s at 0.6, 2.6s at 0.7, 60s at 0.8 and did not finish in seven
minutes at 0.9, where almost every line is its own template. `sweep_corpus.py` runs each
cell under a time budget and prints `--`, because a sweep that goes quiet is
indistinguishable from one that crashed.

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

$ python scripts/fetch_logs.py --list         # the nine-system corpus, and its size
$ python scripts/fetch_logs.py                # fetch it (250 MB, outside the repo)
$ python scripts/sweep_corpus.py              # the table above, per system
```

## The corpus is real

Two of them. The nine Loghub systems above — 2.1 million lines of production logs from
distributed systems, a supercomputer, an operating system, a web server, a mobile app and
a desktop tool — are fetched by `scripts/fetch_logs.py` and **not committed**: they are
250 MB of other people's logs under their own terms, and the script is the reproducible
way to get exactly what was measured.

Committed under `data/` is this machine's own, 1,005 lines captured not generated:

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
uv run pytest -q                    # 60 tests
uv run log-detective cost data/
uv run --extra ui panel serve ui/app.py --show
```

## Layout

```
src/detective/
    templates.py  masking, Drain-style grouping, and the loss accounting
    cli.py        argparse
data/             1,005 real log lines captured from this machine
scripts/          fetch the nine-system Loghub corpus, and sweep it
ui/app.py         Panel dashboard (optional extra)
tests/test_templates.py            39 tests
tests/test_cli_inputs.py           12 tests
tests/test_exact_match_index.py     6 tests
tests/test_sweep_is_not_a_dial.py   3 tests
```
