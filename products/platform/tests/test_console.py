"""The operator console is served, renders, and is wired to the real routes."""

import re

import pytest

from agentplatform import api, graphs
from agentplatform.graphs import END, Graph, Node
from agentplatform.ports import InMemoryBus, InMemoryStore

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def runtime():
    return api.Runtime(
        domain="crm",
        bus=InMemoryBus(),
        store=InMemoryStore(),
        graph=Graph(
            nodes={
                "draft": Node("draft", graphs.LLM, lambda s: {"draft": "hi"}),
                "approve": Node("approve", graphs.INTERRUPT),
                "commit": Node("commit", graphs.TOOL, lambda s: {"committed": True}),
            },
            entry="draft",
            edges={"draft": "approve", "approve": "commit", "commit": END},
        ),
    )


def console(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def test_the_console_is_served_at_the_root():
    body = console(TestClient(api.create_app(runtime())))
    assert "<!doctype html>" in body.lower()


def test_the_product_domain_is_baked_in():
    body = console(TestClient(api.create_app(runtime())))
    assert "crm · agent console" in body
    assert "crm.events" in body


def test_no_template_placeholder_survives():
    # A page shipping "{{DOMAIN}}" to a user is the failure this catches.
    assert "{{" not in console(TestClient(api.create_app(runtime())))


#: `api("/runs")` and ``api(`/approvals/${id}/approve`)`` - both forms, because the
#: pattern here was `api\("(/[a-z]+)"` and the console makes eight distinct calls. It
#: matched the six double-quoted lowercase ones and skipped the two template literals,
#: which are the approve and reject routes - the two this suite has the most reason to
#: check. A checker whose denominator excludes the interesting cases.
_CONSOLE_CALL = re.compile(r"""api\(\s*["`](/[^"`?]+)""")


def _routes_the_console_calls(body: str) -> set[str]:
    """Every path the page requests, with `${...}` left as a FastAPI-shaped parameter."""
    found = set()
    for raw in _CONSOLE_CALL.findall(body):
        found.add(re.sub(r"\$\{[^}]*\}", "{id}", raw))
    return found


def test_every_route_the_console_calls_exists():
    app = api.create_app(runtime())
    client = TestClient(app)
    called = _routes_the_console_calls(console(client))

    assert called == {
        "/health",
        "/runs",
        "/intake",
        "/approvals",
        "/approvals/{id}/approve",
        "/approvals/{id}/reject",
        "/events",
        "/drain",
    }, called

    # Compared against the app's own route table rather than by requesting and reading
    # a status code: a POST to /approvals/nope/approve returns 404 because the *run*
    # does not exist, which is indistinguishable from the route not being registered.
    registered = {
        route.path.replace("{run_id}", "{id}") for route in app.routes if hasattr(route, "path")
    }
    missing = called - registered
    assert missing == set(), f"the console calls routes that are not registered: {missing}"


def test_a_route_the_console_calls_is_reachable_by_the_verb_it_uses(client_free=None):
    """And the two template-literal routes are POST-only, which the old regex never
    reached. 405 means registered-but-wrong-verb, which is still registered."""
    client = TestClient(api.create_app(runtime()))
    for path in ("/health", "/runs", "/approvals", "/events"):
        assert client.get(path).status_code == 200, path
    for path in ("/drain", "/intake"):
        assert client.get(path).status_code == 405, path
    for path in ("/approvals/nope/approve", "/approvals/nope/reject"):
        # Registered: it answers 404 for the run, not 405 for the verb.
        assert client.post(path).status_code == 404, path
        assert client.get(path).status_code == 405, path


def test_the_console_reflects_a_run_waiting_for_approval():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    rt.drain()
    waiting = client.get("/approvals").json()
    assert waiting[0]["awaiting"] == "approve"
    assert waiting[0]["llm_calls"] == 1


def test_the_drain_button_has_a_route_behind_it():
    """And reports outcomes, not just a count of messages taken off the topic.

    `{"handled": 1}` was the same answer for a pass that completed a run and a pass
    where the run failed into the dead-letter queue, and the console drew it as
    progress either way.
    """
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    assert client.post("/drain").json() == {
        "handled": 1,
        "done": 0,
        "failed": 0,
        "awaiting_approval": 1,
    }


def test_the_event_feed_does_not_consume_what_the_projector_reads():
    rt = runtime()
    client = TestClient(api.create_app(rt))
    client.post("/intake", json={"run_id": "r1", "entity": "e1"})
    rt.drain()
    client.post("/approvals/r1/approve")
    assert len(client.get("/events").json()) >= 1
    assert len(client.get("/events").json()) >= 1  # reading it twice is not destructive
    assert len(rt.bus.poll("crm.events", "projector")) == 1


def test_the_page_declares_both_themes():
    body = console(TestClient(api.create_app(runtime())))
    assert "prefers-color-scheme: dark" in body
    assert 'data-theme="dark"' in body


def test_the_page_has_no_build_step():
    body = console(TestClient(api.create_app(runtime())))
    assert "node_modules" not in body
    # Only a Google Fonts stylesheet may be fetched; no script CDNs.
    assert "<script src=" not in body
