"""Every page of every app, actually requested.

`tests/test_apps.py` checks that each app declares `/`, `/run`, `/history`, `/about`,
`/healthz` and `/job/{job_id}`. It never calls one. An independent review found the
consequence: `create_job` was a silent no-op without Redis, so `/run` redirected to a
job page that 404ed while the measurement ran to completion in the background and
reported its result through the same suppressed write - and `/`, `/about`, `/history`
and `/healthz` all kept returning 200, which is what made it look fine. Nothing in the
suite could see it, because nothing in the suite made a request.

These run with no Redis, no Kafka and no model, which is the configuration CI has and
the one the README's "an app boots and serves with none of those present" is about.
`/run` is included: it is the only thing a visitor will actually click, and it is where
that defect was.

`_run_inline` is the one thing held back. It would call Ollama, so the submit path is
followed as far as the redirect and the job record, and the background task is replaced
with one that records having been scheduled.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._platform import base, cache, model  # noqa: E402

APP_FILES = sorted((ROOT / "apps").glob("*/app.py"))


@functools.cache
def load(path: Path):
    """One import per app, not one per test.

    Each `app.py` builds its FastAPI app and loads its engine at import time, which is
    about a second. Re-importing for each of the nine tests below took 114s for this
    module alone - longer than any package suite in the tree - so it is cached. The
    tests share the app object, which is how a server would have it; the two pieces of
    module state that could carry between them, `_run_inline` and `cache._LOCAL_JOBS`,
    are restored by `monkeypatch` and by the autouse fixture respectively.
    """
    name = f"_endpoint_{path.parent.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """No Ollama, whether or not this machine has one.

    `/healthz` reports the model, and the developer machine these were written on has
    Ollama running - so "every dependency absent" was two of three dependencies and a
    coincidence. CI has none, so the assertion would have been right there and the test
    would have been measuring the machine rather than the code.
    """

    async def no_tags():
        return ()

    monkeypatch.setattr(model, "tags", no_tags)
    model.forget_tags()
    yield
    model.forget_tags()


@pytest.fixture(autouse=True)
def no_leftover_jobs():
    """The in-process job fallback is a module global, so one test's run is visible
    to the next. Cleared both sides, because an assertion about an empty history that
    passes only when it runs first is not an assertion."""
    cache._LOCAL_JOBS.clear()
    yield
    cache._LOCAL_JOBS.clear()


def test_the_sweep_covers_all_ten_apps():
    """A parametrised sweep over an empty list passes."""
    assert len(APP_FILES) == 10


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("route", ["/", "/about", "/history"])
def test_every_page_renders_with_nothing_running_behind_it(path, route):
    with TestClient(load(path).app) as client:
        response = client.get(route)
    assert response.status_code == 200, response.text[:300]
    assert "<html" in response.text.lower(), response.text[:300]


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_healthz_reports_every_dependency_as_absent(path):
    with TestClient(load(path).app) as client:
        body = client.get("/healthz").json()

    assert body["redis"] is False
    assert body["kafka"] is False
    assert body["model"] is False
    assert body["cached"] == 0
    # None, not 0.0: nobody has looked anything up. Reporting zero here is the same
    # claim as a cache that missed every single time.
    assert body["cache_hit_rate"] is None
    assert body["cache_lookups"] == 0


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_an_unknown_job_is_a_404_and_not_a_crash(path):
    with TestClient(load(path).app) as client:
        assert client.get("/job/does-not-exist").status_code == 404


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_submitting_a_run_lands_on_a_job_page_that_exists(path, monkeypatch):
    """The defect, as a test.

    `/run` submitted, created a job, redirected - and with no Redis the create was a
    suppressed no-op, so this redirect went to "No such job". Both halves are asserted:
    the redirect target, and that the target renders.
    """
    module = load(path)
    scheduled: list[str] = []

    async def fake_inline(slug, job_id, params, runner):
        scheduled.append(job_id)

    monkeypatch.setattr(base, "_run_inline", fake_inline)

    with TestClient(module.app) as client:
        posted = client.post("/run", data={}, follow_redirects=False)
        assert posted.status_code == 303, posted.text[:300]
        target = posted.headers["location"]
        assert target.startswith("/job/"), target

        page = client.get(target)

    assert page.status_code == 200, f"redirected to a page that does not exist: {target}"
    assert "No such job" not in page.text


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_a_run_with_no_bus_is_recorded_as_having_run_inline(path, monkeypatch):
    """`transport` is how `/history` tells a logged result from an unlogged one.

    It is written with `update_job`, which was suppressed on the same path, so the
    history page could not distinguish them either.
    """
    module = load(path)

    async def fake_inline(slug, job_id, params, runner):
        return None

    monkeypatch.setattr(base, "_run_inline", fake_inline)

    with TestClient(module.app) as client:
        job_id = (
            client.post("/run", data={}, follow_redirects=False)
            .headers["location"]
            .removeprefix("/job/")
        )

    assert cache._LOCAL_JOBS[job_id]["transport"] == "inline"
    assert cache._LOCAL_JOBS[job_id]["app"] == module.SLUG


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_the_result_fragment_says_still_running_rather_than_failing(path, monkeypatch):
    """job.html fetches this, so a 500 here is a broken page rather than a blank one."""
    module = load(path)

    async def fake_inline(slug, job_id, params, runner):
        return None

    monkeypatch.setattr(base, "_run_inline", fake_inline)

    with TestClient(module.app) as client:
        job_id = (
            client.post("/run", data={}, follow_redirects=False)
            .headers["location"]
            .removeprefix("/job/")
        )
        fragment = client.get(f"/job/{job_id}/result")

    assert fragment.status_code == 200
    assert "Still running" in fragment.text


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_a_submitted_run_shows_up_on_the_history_page(path, monkeypatch):
    """The in-process fallback has to reach `/history`, not only the job page.

    `recent_jobs` merges Redis and local; with no Redis the local half is the whole
    population, and if it were missed the page would be empty for a run the job page
    shows.
    """
    module = load(path)

    async def fake_inline(slug, job_id, params, runner):
        return None

    monkeypatch.setattr(base, "_run_inline", fake_inline)

    with TestClient(module.app) as client:
        job_id = (
            client.post("/run", data={}, follow_redirects=False)
            .headers["location"]
            .removeprefix("/job/")
        )
        history = client.get("/history")

    assert history.status_code == 200
    assert job_id in history.text, "the run is not on the page that lists runs"


# -- a finished job whose result the template cannot render -------------------------
#
# It raised out of Jinja and came back as a 500, and the page showed nothing. The
# page then sits on "Still running…" for a job that finished - the worst of the
# available outcomes, because the only thing the reader can tell is the one thing that
# is false. Every path into it is ordinary: a result cached by an earlier version of
# the app, which job state in Redis outlives a deploy to produce; a graph that exited
# early and finished with `{}`; a key renamed in the app and not in its template.
#
# Driven through `cache._LOCAL_JOBS`, the in-process fallback `get_job` merges over
# Redis, so no broker is needed and the route is the real one.

DRIFTED_RESULTS = {
    "empty": "{}",
    "a renamed key": '{"unexpected": 1}',
    "not an object": '"a plain string"',
    "not json at all": "oops",
}


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("shape", sorted(DRIFTED_RESULTS))
def test_a_result_the_template_cannot_render_is_a_fragment_not_a_500(path, shape):
    module = load(path)
    cache._LOCAL_JOBS["j"] = {
        "status": "done",
        "slug": module.app.title,
        "result": DRIFTED_RESULTS[shape],
    }
    with TestClient(module.app, raise_server_exceptions=False) as client:
        response = client.get("/job/j/result")

    assert response.status_code == 200, (shape, response.text[:200])
    # Either the template coped, or it said so. What it may never do is claim a
    # finished job is still running, which is what a 500 made the page show.
    assert "Still running" not in response.text, shape
    if "cannot display its result" in response.text:
        assert "Keys in it:" in response.text, shape


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_a_job_that_has_not_finished_still_says_so(path):
    """The fallback must not swallow the running case. Those are different answers,
    and the defect was one of them being shown for the other."""
    module = load(path)
    cache._LOCAL_JOBS["j"] = {"status": "running", "slug": module.app.title}
    with TestClient(module.app) as client:
        response = client.get("/job/j/result")
    assert response.status_code == 200
    assert "Still running" in response.text


# -- the stream's terminal condition -----------------------------------------------
#
# `gen()` has a fast path for a job that finished before the browser opened the stream,
# and it asked `status == "done"` while the loop below it ends on `"done"` or `"error"`.


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_the_stream_ends_for_a_job_that_failed(path, monkeypatch):
    """A failed job must close the stream, not wait for a message that cannot come.

    `gen()`'s pre-check - for a job that finished before the browser opened the stream -
    asked `status == "done"`, while the loop under it ends on `"done"` or `"error"`. On
    that asymmetry a FAILED job fell through to `subscribe_progress`.

    With Redis reachable, that subscribes to the job's channel and iterates
    `pubsub.listen()`, waiting to be published to. A run that has already ended will never
    publish again, so the connection stays open for ever and the page's progress never
    resolves - on the one outcome the reader most needs to be told about.

    `subscribe_progress` is replaced with one that never yields, because that is what
    `pubsub.listen()` IS for an ended job. Without the substitution this test passes in
    both directions: with no Redis the real one falls to `_local_progress`, which reads
    the job out of this process and ends the stream by itself, so the pre-check's decision
    makes no difference and the test is measuring the fallback instead of the fix.

    The read is in a daemon thread with a join deadline, because the defect IS a stream
    that never ends: read inline, this would hang rather than fail, which is the same
    observable outcome as the bug.
    """
    module = load(path)

    async def never_yields(job_id):
        # What `pubsub.listen()` does for a job whose run is over: waits.
        await asyncio.sleep(3600)
        yield {}  # pragma: no cover - never reached

    monkeypatch.setattr(cache, "subscribe_progress", never_yields)
    cache._LOCAL_JOBS["failed"] = {
        "status": "error",
        "slug": module.app.title,
        "note": "ollama is not reachable",
    }

    lines: list[str] = []

    def read() -> None:
        with (
            TestClient(module.app) as client,
            client.stream("GET", "/job/failed/stream") as response,
        ):
            assert response.status_code == 200
            for line in response.iter_lines():
                lines.append(line)
                if len(lines) >= 6:
                    break

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout=30)
    assert not reader.is_alive(), (
        "the stream for a failed job did not end within 30s: it fell through to "
        "subscribe_progress and is waiting for a message the finished run will never send"
    )
    body = "\n".join(lines)
    assert "event: done" in body, f"the stream never ended: {body!r}"


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_the_terminal_event_carries_the_status(path):
    """`job.html` reads `d.status` and `d.note` off this event.

    The fast path used to send `{"job_id": ...}` alone, so `d.status` was undefined and
    the handler took its `else` branch - "complete", in green - for any job that had
    finished before the stream opened, whatever the outcome was.
    """
    module = load(path)
    cache._LOCAL_JOBS["failed2"] = {
        "status": "error",
        "slug": module.app.title,
        "note": "a stated reason",
    }
    with (
        TestClient(module.app) as client,
        client.stream("GET", "/job/failed2/stream") as response,
    ):
        payload = ""
        for line in response.iter_lines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                break
    sent = json.loads(payload)
    assert sent.get("status") == "error", sent
    assert sent.get("note") == "a stated reason", sent
    assert sent.get("job_id") == "failed2", sent


# -- the result template on a result that is the right shape -----------------------
#
# `job_result` now catches `Exception` around `TemplateResponse` and returns a 200
# fragment, which is right for a drifted result and removed the only signal a template
# broken for the CORRECT shape ever had: it would ship as a muted paragraph with
# nothing failing. An independent review raised exactly that, having probed it by hand.
#
# The two apps with a committed run are the two that can be checked without a model.
# `apps/results/*.json` is what the real run produced, so feeding it back through the
# route is the closest thing to a rendered page that a test can assert.

#: App -> the committed file that is a RUN of it, in the shape `runner` returns.
#:
#: `03_vuln_baseline.json` is deliberately not here. `apps/results/README.md` describes
#: it as "the Devign test split's class balance and two sampling windows" - dataset
#: facts, which is a different artefact from a run, and the only one that can be
#: committed because `runner`'s `full` block is built from model answers. Feeding it to
#: the result template is a type error, not a test.
#:
#: That gap is why `tests/test_result_templates.py` exists: an app whose run cannot be
#: committed is exactly the one whose template rots unnoticed, and app 03's did - it
#: read `result.beats_baseline` for four lines after the runner split that field in two.
COMMITTED_RUNS = {
    "01_localizer": None,
    "02_false_accepts": "02_false_accepts.json",
    "03_vuln_baseline": None,
}


def _committed(slug: str):
    import json

    name = COMMITTED_RUNS.get(slug)
    if name is None:
        return None
    path = ROOT / "apps" / "results" / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_the_result_template_renders_the_run_this_app_committed(path):
    """A well-shaped result has to render, and has to render as the result.

    The fallback fragment is indistinguishable from a successful render to any test
    that only checks the status code, so this asserts the fallback is NOT what came
    back - which is the assertion the catch-all would otherwise have silenced.
    """
    slug = path.parent.name
    run = _committed(slug)
    if run is None:
        pytest.skip(f"{slug} has no committed run to render")

    module = load(path)
    # The committed file is keyed by split for app 02 and is one run for app 03; both
    # shapes go in as the job's `result` exactly as the worker would have stored them.
    payloads = run.values() if slug == "02_false_accepts" else [run]
    for n, result in enumerate(payloads):
        cache._LOCAL_JOBS.clear()
        cache._LOCAL_JOBS["j"] = {
            "status": "done",
            "slug": module.app.title,
            "result": json.dumps(result),
        }
        with TestClient(module.app, raise_server_exceptions=False) as client:
            response = client.get("/job/j/result")

        assert response.status_code == 200, (slug, n, response.text[:300])
        assert "cannot display its result" not in response.text, (
            f"{slug}: the result template could not render the run this app committed, "
            "and the fallback made it a 200"
        )
        assert "Still running" not in response.text, (slug, n)
        # Something from the run itself, so an empty page cannot pass.
        assert len(response.text.strip()) > 200, (slug, n, response.text[:200])


def test_the_two_apps_with_a_committed_run_are_the_ones_named():
    """A sweep whose every case skips passes. This says which two do not."""
    renderable = [slug for slug in COMMITTED_RUNS if _committed(slug) is not None]
    assert renderable == ["02_false_accepts"], renderable


def test_the_committed_file_that_is_not_a_run_is_not_one():
    """App 03 has a committed summary and is excluded, which needs to be a fact.

    This asserted `COMMITTED_RUNS["03_vuln_baseline"] is None` - a read of the dict
    literal four screens up, in the file that defines it. It cannot fail, and an
    exclusion asserted from the table that performs it is indistinguishable from an
    oversight.

    The claim is that the file is dataset facts rather than a run, so that is what is
    checked: its keys are not the keys `runner` returns, which is what makes feeding it
    to the result template a type error rather than a test.
    """
    import ast
    import json

    path = ROOT / "apps" / "results" / "03_vuln_baseline.json"
    assert path.is_file(), "the file the exclusion is about is gone"
    committed = set(json.loads(path.read_text(encoding="utf-8")))
    assert committed, path

    tree = ast.parse((ROOT / "apps" / "03_vuln_baseline" / "app.py").read_text(encoding="utf-8"))
    runners = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "runner"
    ]
    assert len(runners) == 1
    returned = {
        key.value
        for node in ast.walk(runners[0])
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        for key in node.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert returned, "the runner's return is no longer a dict literal"
    # Not "shares no keys": `rows` and `label_noise` are facts about the dataset and
    # appear in both. What makes it not a run is that most of what the runner produces
    # is absent from it - the model-answer blocks the template is built around.
    missing = returned - committed
    assert len(missing) > len(returned) / 2, (
        "the committed file now holds most of what `runner` returns, so it may be a run "
        f"after all; it is missing only {sorted(missing)}"
    )
    assert {"full", "parsed"} <= missing, sorted(missing)

    # And the reason is where a reader looking at the table will find it.
    source = Path(__file__).read_text(encoding="utf-8")
    table = source[: source.index("COMMITTED_RUNS = {")]
    assert "03_vuln_baseline.json` is deliberately not here" in table
    assert "apps/results/README.md" in table
