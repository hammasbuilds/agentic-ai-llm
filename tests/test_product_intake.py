"""Every product's `/intake`, with a control key in the body.

The approval interrupt was bypassable from the request body: `graphs.APPROVED` is the
string `"_approved"`, the gate reads it off the working state, and `POST /intake` filled
that state from `body["payload"]` unfiltered. A run submitted with
`{"payload": {"_approved": true}}` went past the interrupt into the tool node with no
pause, no checkpoint and no row in `/approvals`.

`products/platform/tests/test_api.py` covers the shared path on a synthetic graph. This
covers the claim as made: twenty products, each with its own graph, each refusing it -
because "the human approves before anything leaves the building" is said in twenty
READMEs and the thing enforcing it is one `if` in one file.

Every product is driven with `Recorded`, which raises on an unscripted prompt, so none
of these can reach a real model. A refused intake never runs the graph at all, which is
why no script is needed for the refusal half.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for src in sorted((ROOT / "products").glob("*/src")):
    sys.path.insert(0, str(src))

pytest.importorskip("fastapi")

from agentplatform import api, graphs  # noqa: E402
from agentplatform.llm import Recorded  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

#: Product directory -> the package under its `src/`.
PRODUCTS = {
    path.name: next(
        p.name for p in (path / "src").iterdir() if p.is_dir() and p.name != "__pycache__"
    )
    for path in sorted((ROOT / "products").glob("[0-9]*"))
    if (path / "src").is_dir()
}

#: Keys the graph reserves. `_approved` is the one that mattered; the others are here so
#: a rename or an addition does not reopen the hole, which is the likelier of the two.
CONTROL_KEYS = ("_approved", "_checkpoint", "_next_node")


def client_for(package: str) -> TestClient:
    """One product's app, on in-memory ports and a model that cannot be reached.

    Through the product's own `app.runtime(model)` rather than `graph.build(model)`:
    all twenty share the first signature and `01_revenue-desk` does not share the
    second, which it supplies default sources for. Building the graph directly made
    this sweep cover nineteen and error on the twentieth - and a sweep that errors on
    one member is the thing this file exists to catch elsewhere.
    """
    module = importlib.import_module(f"{package}.app")
    return TestClient(api.create_app(module.runtime(Recorded({}))))


def test_there_are_twenty_products_to_check():
    """A parametrised sweep over an empty mapping passes."""
    assert len(PRODUCTS) == 20, sorted(PRODUCTS)


def test_the_gate_reads_the_key_this_file_is_about():
    """So a rename of `graphs.APPROVED` fails here rather than silently widening the
    hole this closes."""
    assert graphs.APPROVED == "_approved"
    assert graphs.APPROVED in CONTROL_KEYS


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
@pytest.mark.parametrize("key", CONTROL_KEYS)
def test_a_control_key_in_the_body_is_refused(product, package, key):
    reply = client_for(package).post(
        "/intake", json={"run_id": "r-bad", "entity": "e1", "payload": {key: True}}
    )
    assert reply.status_code == 422, (product, key, reply.text)
    assert key in reply.json()["detail"], (product, key)


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_a_refused_intake_leaves_no_run_behind(product, package):
    """A 422 that still created the row would leave a half-submitted run to be drained."""
    client = client_for(package)
    client.post("/intake", json={"run_id": "r-bad", "entity": "e1", "payload": {"_approved": 1}})
    assert client.get("/runs/r-bad").status_code == 404, product


@pytest.mark.parametrize("product,package", sorted(PRODUCTS.items()))
def test_an_ordinary_payload_is_still_accepted(product, package):
    """The other half: a gate that refuses everything is not a working gate.

    Only the accept is checked here, not the run - draining needs each product's own
    scripted prompts, which its own suite has.
    """
    reply = client_for(package).post(
        "/intake", json={"run_id": "r-ok", "entity": "e1", "payload": {"note": "hello"}}
    )
    assert reply.status_code == 202, (product, reply.text)
