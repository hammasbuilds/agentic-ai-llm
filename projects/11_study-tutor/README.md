<h1 align="center">study-tutor</h1>
<p align="center"><i>Spaced repetition where the scheduler is arithmetic and the model only writes questions</i></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-28-success" alt="tests">
</p>

---

## Results

**One lapse costs SM-2 the card's entire history. It costs FSRS about a third of one
interval.**

Interval in days after a single "again" on a card established by six successful reviews:

```
  sm2   [1, 1, 6, 14, 32]
  fsrs  [18, 48, 119, 278, 615]
```

SM-2 sends a card you had spaced to **238 days** back to **tomorrow**, and then walks it
out again from scratch. FSRS reduces stability and resumes at 18 days. The card was
forgotten once; SM-2 acts as though it was never learnt.

Aggregate over a simulated year, 50 cards, averaged across 5 seeds:

| scheduler | reviews | lapses | recall at review | final recall |
|---|---|---|---|---|
| sm2 | 828 | 160 | 81.5% | 96.7% |
| fsrs | 796 | 173 | 78.8% | 93.9% |

The aggregate difference is small - about 4% fewer reviews - and that is worth stating
plainly, because the lapse table above looks far more dramatic than the yearly total. The
per-card behaviour differs enormously; the summed workload does not.

## Why the scheduler is not a prompt

An interval is arithmetic over a memory model. It is reproducible, testable, and wrong in
ways you can detect. Ask a language model when to review something and you get a
plausible number with no memory model behind it, a different number next time, and no way
to check either.

So the split here is absolute: **the scheduler is code, the model writes questions.**
There is a test asserting that scheduling the same card twice returns exactly the same
result, which is precisely the property an LLM cannot offer.

## Input / Output

**In:** a deck as JSON, and a grade per card (1 again, 2 hard, 3 good, 4 easy).

**Out:** the next interval and due date for each card, computed from its memory state.

```
$ study-tutor due deck.json
$ study-tutor review deck.json --scheduler fsrs
$ study-tutor compare                      # the tables above
$ uv run --extra ui reflex run             # the Reflex UI
```

## What is actually implemented

**SM-2** as published in 1987 - kept honest rather than quietly improved, because a
comparison against a repaired SM-2 would not be a comparison with what flashcard apps
actually run.

**FSRS-4.5** with the published default weights. They are not tuned here: tuning them
without a real review log would be inventing a memory model and calling it a measurement.

The forgetting curve is `(1 + t/9s)^-1`, and `_interval_for` inverts it to find when
recall reaches the target retention. There is a test that schedules a card and then
checks the predicted recall at that interval is 0.9 - the scheduler and the memory model
have to agree or both are wrong.

## What I wrote vs what I installed

**Installed: nothing.** `dependencies = []`. Both schedulers, the forgetting curve and
the simulation are arithmetic. `reflex` is an optional extra used only by the UI.

## Scope

- **No question generation.** The part a model would do is the part that is not here; the
  deck is a JSON file you write.
- **The weights are not tuned.** FSRS is designed to be optimised against your own review
  log. With no such log, the published defaults are used and the tuner is absent.
- **No real learner data.** Every number here comes from a simulation against a stated
  memory model, and none of it is a claim about human memory.
- **No sub-day scheduling**, no learning steps, no burying siblings - the things a real
  flashcard app needs and this does not have.
- **Single deck, single user, no sync.**

## Run it

```bash
uv run pytest -q                 # 28 tests
uv run study-tutor compare
uv run --extra ui reflex run
```

## Layout

```
src/tutor/
    scheduler.py  SM-2 and FSRS-4.5, the forgetting curve, deck helpers
    simulate.py   identical review histories through both schedulers
    cli.py        argparse
ui/app.py         Reflex UI (optional extra)
tests/test_scheduler.py   28 tests
```
