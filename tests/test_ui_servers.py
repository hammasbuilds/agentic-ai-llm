"""The three zero-install UI servers, which had no tests at all.

`RUNNING.md` recommends them and nothing imported one: `grep -rln "ui.serve" tests/`
found nothing across the whole repository. An independent review drove them with curl
and two of the three died on a malformed query parameter - not a 400, a closed socket,
which curl reports as HTTP 000 and a browser shows as nothing at all:

  * `release-captain`'s `?since=abc` raised `ValueError` out of the handler, and
    `?since=-5` was accepted and silently changed the population the verdict is
    computed over;
  * `compliance-auditor`'s `?path=C:/Windows/Temp` raised `PermissionError`.

And all three defaulted a missing `path` to `"."`, so a request with no path surveyed
whatever directory the server happened to be started in and answered with a confident
figure about it - `{"rate": 0.0833}` from the auditor, "1 licence file(s)" from
contract-reader - which a reader cannot tell apart from a figure about the folder they
meant.

The handlers are driven directly rather than over a socket: the request line is parsed
by `BaseHTTPRequestHandler`, so a fake `wfile` and a hand-set `path` reach exactly the
code the review attacked, and no port is opened. A server on a port would also be the
one thing this repository has been asked not to start.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Each server, and the endpoint whose query string the review broke.
SERVERS = {
    "05_release-captain": "/api/gate",
    "07_compliance-auditor": "/api/audit",
    "10_contract-reader": "/api/survey",
}


def load(project: str):
    """`ui/serve.py` by path: it is a script beside a package, not in one."""
    path = ROOT / "projects" / project / "ui" / "serve.py"
    assert path.is_file(), path
    sys.path.insert(0, str(ROOT / "projects" / project / "src"))
    spec = importlib.util.spec_from_file_location(f"ui_{project.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Captured:
    """One request through a handler, without a socket."""

    def __init__(self, module, path: str, root: Path | None = None):
        handler = module.Handler
        self.status: int | None = None
        self.body = b""
        self.headers: dict[str, str] = {}

        probe = handler.__new__(handler)
        probe.path = path
        probe.wfile = io.BytesIO()
        probe.rfile = io.BytesIO()
        probe.request_version = "HTTP/1.1"
        probe.client_address = ("127.0.0.1", 0)
        if root is not None and hasattr(handler, "root"):
            probe.root = root

        def send_response(code, message=None):
            self.status = code

        def send_header(key, value):
            self.headers[key] = value

        probe.send_response = send_response
        probe.send_header = send_header
        probe.end_headers = lambda: None
        probe.log_message = lambda *a, **k: None
        probe.do_GET()
        self.body = probe.wfile.getvalue()

    def json(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


def test_all_three_servers_are_covered():
    """A sweep over an empty mapping passes. `RUNNING.md` names three."""
    assert len(SERVERS) == 3
    for project in SERVERS:
        assert (ROOT / "projects" / project / "ui" / "serve.py").is_file(), project


#: The two endpoints that take a folder. `release-captain`'s `/api/gate` takes a `repo`
#: name under a root it was started with, so it has no `path` to default - which is why
#: it is named here rather than filtered out by a condition at runtime.
PATH_ENDPOINTS = {
    "07_compliance-auditor": "/api/audit",
    "10_contract-reader": "/api/survey",
}


@pytest.mark.parametrize("project,endpoint", sorted(PATH_ENDPOINTS.items()))
def test_a_request_with_no_path_is_refused_rather_than_answered_about_cwd(project, endpoint):
    """Both defaulted to `"."`.

    So the answer was about whatever directory the server was started in, and it looked
    exactly like an answer about the folder the reader asked for: `{"rate": 0.0833}`
    from the auditor over its own package source, "1 licence file(s)" from
    contract-reader.
    """
    module = load(project)
    captured = Captured(module, endpoint, root=ROOT)
    assert captured.status == 400, (project, captured.status, captured.body[:200])
    assert "required" in captured.json()["error"], captured.json()


# `""` is not here: `parse_qs` drops an empty value, so `?since=` takes the default of
# 8 and never reaches the parse. That is correct, and asserting 400 for it would be
# asserting a bug.
@pytest.mark.parametrize("value", ["abc", "1.5", "-5", "0", "99999", "1e9", "eight"])
def test_a_malformed_since_is_a_four_hundred_not_a_dead_socket(value):
    """`int((params.get("since") or ["8"])[0])` raised out of the handler.

    A ValueError there closes the connection with no response, which curl reports as
    HTTP 000. `-5` and `0` were worse: accepted, and they change the window the verdict
    is computed over without saying so.
    """
    module = load("05_release-captain")
    captured = Captured(module, f"/api/gate?repo=x&since={value}", root=ROOT)
    assert captured.status == 400, (value, captured.status)
    detail = captured.json()["error"]
    assert "since" in detail or "unknown repository" in detail, detail


def test_an_empty_since_falls_back_to_the_default():
    """`?since=` is dropped by `parse_qs`, so the default applies and the request gets
    as far as the repository lookup. Asserted so the distinction is recorded rather
    than rediscovered."""
    module = load("05_release-captain")
    captured = Captured(module, "/api/gate?repo=no-such-repo&since=", root=ROOT)
    assert captured.status == 404
    assert "unknown repository" in captured.json()["error"]


def test_a_since_inside_the_range_is_still_accepted():
    """A bound that rejects everything is not a bound. The repository is unknown here,
    so a 404 is the right answer and proves `since` parsed."""
    module = load("05_release-captain")
    captured = Captured(module, "/api/gate?repo=no-such-repo&since=8", root=ROOT)
    assert captured.status == 404, captured.status
    assert "unknown repository" in captured.json()["error"]


@pytest.mark.parametrize(
    "project,endpoint",
    [
        ("07_compliance-auditor", "/api/audit"),
        ("10_contract-reader", "/api/survey"),
    ],
)
def test_a_path_that_is_a_file_is_refused(project, endpoint, tmp_path):
    module = load(project)
    a_file = tmp_path / "notes.txt"
    a_file.write_text("x", encoding="utf-8")
    captured = Captured(module, f"{endpoint}?path={a_file.as_posix()}")
    assert captured.status == 400, (project, captured.status)
    assert "not a directory" in captured.json()["error"]


@pytest.mark.parametrize(
    "project,endpoint",
    [
        ("07_compliance-auditor", "/api/audit"),
        ("10_contract-reader", "/api/survey"),
    ],
)
def test_a_path_that_does_not_exist_is_refused(project, endpoint, tmp_path):
    module = load(project)
    captured = Captured(module, f"{endpoint}?path={(tmp_path / 'nope').as_posix()}")
    assert captured.status == 400, (project, captured.status)


@pytest.mark.parametrize("project,endpoint", sorted(SERVERS.items()))
def test_an_unknown_route_is_handled(project, endpoint):
    """A 404, not a traceback."""
    module = load(project)
    captured = Captured(module, "/api/does-not-exist", root=ROOT)
    assert captured.status in (400, 404), (project, captured.status)
