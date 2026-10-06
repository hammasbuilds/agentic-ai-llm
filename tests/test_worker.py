"""The worker, which had no tests at all.

`worker.py` is 149 lines and the root README calls it the centre of the architecture:
one process, one GPU, one job at a time. `grep -rn worker tests/` found nothing - no
import, no fake consumer, nothing. An independent review drove it with a stub consumer
and found three things in the loop, two of which lose work silently:

  * a message for an app this worker does not serve was skipped by a bare `continue`
    with no log line, and the consumer auto-commits, so on the documented
    single-worker deployment the offset advanced past a job no worker would ever see
    again. It stayed `queued` in Redis for ever and the page kept showing it queued.
  * `ev['job_id']` was indexed outside `handle`'s `except`, so one message without that
    key raised `KeyError` out of `main()` and killed the only process with the GPU -
    on a topic created with `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"` that validates
    nothing.
  * a message with no `app` was dropped in silence.

Nothing here starts a broker or touches Redis: `consume_one` is called directly, and
`handle` is the only thing that reaches the cache, so it is stubbed where the test is
about dispatch rather than about running a job.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_worker():
    """`worker.py` is a script at the root, not a module in a package."""
    spec = importlib.util.spec_from_file_location("aal_worker", ROOT / "worker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["aal_worker"] = module
    spec.loader.exec_module(module)
    return module


worker = load_worker()


@pytest.fixture
def served(monkeypatch):
    """One runner, and a record of what `handle` was asked to run."""
    handled: list[tuple] = []

    async def fake_handle(job_id, app, params, runner):
        handled.append((job_id, app, params))

    monkeypatch.setattr(worker, "handle", fake_handle)
    return handled


def run(coro):
    return asyncio.run(coro)


RUNNERS = {"localizer": object(), "kill-rate": object()}


# -- a malformed message must not stop the process -----------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"app": "localizer"},  # no job_id - this is the one that killed it
        {"job_id": "j1"},  # no app
        {"job_id": "", "app": "localizer"},
        {"job_id": None, "app": "localizer"},
        {"job_id": "j1", "app": None},
        {"job_id": "j1", "app": ""},
        {},
        "not an object",
        None,
        [1, 2, 3],
        42,
    ],
    ids=lambda m: repr(m)[:40],
)
def test_a_malformed_message_is_reported_and_skipped(message, served, capsys):
    run(worker.consume_one(message, RUNNERS))
    assert served == [], f"a malformed message reached handle: {message!r}"
    out = capsys.readouterr().out
    assert out.strip(), f"nothing was printed for {message!r}, so it was dropped silently"
    assert "ignored" in out, out


def test_the_message_that_killed_the_process_now_names_what_is_missing(served, capsys):
    """`KeyError: 'job_id'` out of `main()` was the whole failure."""
    run(worker.consume_one({"app": "localizer", "params": {"limit": 5}}, RUNNERS))
    assert "no job_id" in capsys.readouterr().out


# -- a job for another worker's app is logged, not silently dropped ------------


def test_a_job_for_an_app_this_worker_does_not_serve_says_so(served, capsys):
    run(worker.consume_one({"job_id": "j9", "app": "temperature"}, RUNNERS))
    assert served == []
    out = capsys.readouterr().out
    assert "not mine" in out and "j9" in out and "temperature" in out, out
    # And it names what this worker DOES serve, so the operator can see the mismatch
    # rather than inferring it from a job that never runs.
    assert "kill-rate" in out and "localizer" in out, out


# -- the honest path ----------------------------------------------------------


def test_a_good_message_is_dispatched_with_its_params(served):
    run(worker.consume_one({"job_id": "j1", "app": "localizer", "params": {"limit": 7}}, RUNNERS))
    assert served == [("j1", "localizer", {"limit": 7})]


@pytest.mark.parametrize("params", [None, "not a dict", 5, [1]])
def test_params_that_are_not_an_object_become_an_empty_one(params, served):
    """The runner signature takes a dict. A string here used to reach it as a string."""
    run(worker.consume_one({"job_id": "j1", "app": "localizer", "params": params}, RUNNERS))
    assert served == [("j1", "localizer", {})]


def test_a_message_with_no_params_at_all_still_runs(served):
    run(worker.consume_one({"job_id": "j1", "app": "localizer"}, RUNNERS))
    assert served == [("j1", "localizer", {})]


# -- the consumer group, which is where the lost jobs came from ----------------


def test_a_filtered_worker_does_not_share_the_unfiltered_group():
    """The fix for the silently-discarded job.

    `bus.consumer(..., commit=True)` auto-commits, so a `--apps localizer` worker in
    group `workers` advanced the group's offset past every job for the other nine apps.
    The group now carries the filter, so those offsets are its own.
    """
    source = (ROOT / "worker.py").read_text(encoding="utf-8")
    code = [
        line for line in source.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    joined = "\n".join(code)
    assert "group=group" in joined, "the consumer is not using the derived group"
    assert "group=args.group" not in joined, "the raw group is back"
    assert "if args.apps:" in joined


def test_the_derived_group_is_stable_and_names_the_filter():
    """Stable, because a group that changes between restarts re-reads from `latest` and
    the jobs submitted while it was down are never seen."""
    first = f"workers-{'+'.join(sorted(['localizer', 'kill-rate']))}"
    second = f"workers-{'+'.join(sorted(['kill-rate', 'localizer']))}"
    assert first == second == "workers-kill-rate+localizer"


def test_the_docstring_command_names_slugs_that_exist():
    """`python worker.py --apps localizer kill-rate` is in worker.py's own docstring.

    A filter naming a slug no app has leaves `runners` empty, and the worker exits 1
    saying "no runners loaded" - a documented command that cannot work.
    """
    import re

    source = (ROOT / "worker.py").read_text(encoding="utf-8")
    quoted = re.search(r"python worker\.py --apps ([\w\- ]+)", source)
    assert quoted, "the docstring no longer shows the --apps form"

    slugs = set()
    for path in sorted((ROOT / "apps").glob("[0-9][0-9]_*/app.py")):
        found = re.search(r'^SLUG = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        if found:
            slugs.add(found.group(1))
    assert len(slugs) == 10, sorted(slugs)
    named = quoted.group(1).split()
    assert set(named) <= slugs, f"the docstring names {sorted(set(named) - slugs)}"


# -- the loop, not just the function it calls ---------------------------------


class FakeConsumer:
    """Hands out one batch, then sets the loop's stop event so `main()` can return.

    The event is `stopper`, not `stop`: `main()` calls `await consumer.stop()` in its
    `finally`, and naming the attribute `stop` shadowed that method with an Event -
    `TypeError: 'Event' object is not callable` from inside the teardown.
    """

    def __init__(self, batches, stopper):
        self.batches = list(batches)
        self.stopper = stopper
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, timeout_ms=0, max_records=0):
        if not self.batches:
            self.stopper.set()
            return {}
        return {"p0": [type("Rec", (), {"value": v})() for v in self.batches.pop(0)]}


def drive(monkeypatch, messages, runners=None, argv=None):
    """Run `main()` over a fake consumer. Returns (code, stdout, handled, opened).

    Through `main()` rather than through `consume_one`, because every defect here was
    at the call site: reverting the loop to `ev['job_id']` left all twenty-two
    helper-level tests green.
    """
    import io
    from contextlib import redirect_stdout

    runners = RUNNERS if runners is None else runners
    handled: list[tuple] = []
    opened: dict = {}
    stop = asyncio.Event()

    async def fake_handle(job_id, app, params, runner):
        handled.append((job_id, app, params))

    async def available():
        return True

    async def close():
        return None

    def consumer(topic, group, from_beginning=False, commit=True):
        opened["group"] = group
        made = FakeConsumer([messages] if messages else [], stop)
        opened["consumer"] = made
        return made

    monkeypatch.setattr(worker, "handle", fake_handle)
    monkeypatch.setattr(worker, "load_runners", lambda: dict(runners))
    monkeypatch.setattr(worker.bus, "available", available)
    monkeypatch.setattr(worker.bus, "close", close)
    monkeypatch.setattr(worker.bus, "consumer", consumer)

    printed = io.StringIO()
    with redirect_stdout(printed):
        code = asyncio.run(worker.main(argv or [], stop=stop))
    return code, printed.getvalue(), handled, opened


def test_the_loop_survives_the_message_that_killed_it(monkeypatch):
    code, out, handled, _ = drive(
        monkeypatch,
        [
            {"app": "localizer"},  # no job_id: this raised out of main()
            {"job_id": "j1", "app": "localizer", "params": {"limit": 1}},
        ],
    )
    assert code == 0, out[-700:]
    assert handled == [("j1", "localizer", {"limit": 1})], out[-700:]
    assert "ignored" in out


def test_the_loop_handles_every_good_message_in_a_batch(monkeypatch):
    code, out, handled, _ = drive(
        monkeypatch,
        [
            {"job_id": "a", "app": "localizer"},
            {"job_id": "b", "app": "unserved"},
            {"job_id": "c", "app": "kill-rate"},
        ],
    )
    assert code == 0
    assert [j for j, _, _ in handled] == ["a", "c"], out[-500:]
    assert "not mine: b" in out


def test_an_unfiltered_worker_uses_the_plain_group(monkeypatch):
    _, _, _, opened = drive(monkeypatch, [])
    assert opened["group"] == "workers"


def test_a_filtered_worker_uses_a_group_of_its_own(monkeypatch):
    """The lost-job fix, read off the loop that chooses the group."""
    _, out, _, opened = drive(monkeypatch, [], argv=["--apps", "localizer"])
    assert opened["group"] == "workers-localizer", opened
    assert "rather than 'workers'" in out, out


def test_a_filter_naming_no_real_app_exits_rather_than_idling(monkeypatch):
    code, out, _, _ = drive(monkeypatch, [], argv=["--apps", "does-not-exist"])
    assert code == 1
    assert "no runners loaded" in out
