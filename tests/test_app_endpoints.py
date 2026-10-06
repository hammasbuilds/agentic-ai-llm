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

import functools
import importlib.util
import sys
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
    """HTMX swaps this in, so a 500 here is a broken page rather than a blank one."""
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
