"""Boot every product on a real ASGI server and exercise its HTTP surface.

The test suites use a TestClient, which never binds a socket. This starts
uvicorn for each product in turn, drives a full intake -> drain -> approve cycle
over HTTP, and shuts it down again — so "it serves" is a thing that was
observed rather than assumed.

    python scripts/smoke_serve.py
"""

from __future__ import annotations

import importlib
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from product_spec import spec_for  # noqa: E402

PRODUCTS = sorted(d for d in ROOT.iterdir() if d.is_dir() and d.name[0].isdigit())

PKGS = {
    "revenue",
    "ward",
    "onedesk",
    "ledger",
    "comms",
    "oncall",
    "hiredesk",
    "biddesk",
    "hermes",
    "kycfloor",
    "watchtower",
    "powerguard",
    "swarmlab",
    "graphclinic",
    "claimsfloor",
    "shelfops",
    "fleetdesk",
    "campusops",
    "agridesk",
    "driftwatch",
}
PKGS |= {f"{p}.{s}" for p in PKGS for s in ("app", "graph", "agents", "domain")}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(product: Path) -> dict:
    import httpx
    import uvicorn

    paths = [str(product / "src"), str(ROOT / "platform" / "src"), str(product / "tests")]
    for p in paths:
        sys.path.insert(0, p)
    for mod in list(sys.modules):
        if mod.startswith(("test_graph", "agentplatform")) or mod in PKGS:
            del sys.modules[mod]

    try:
        tg = importlib.import_module("test_graph")
        from agentplatform import api
        from agentplatform.llm import Recorded

        # Through the shared adapter, which is what `capture.py` has used since
        # nineteen products moved to a `StandardProductTests` subclass. This read
        # `tg.payload()` directly, so it raised AttributeError on nineteen of twenty -
        # after writing the error into `served.json`, the file this script exists to
        # produce and the README points at.
        spec = spec_for(tg)
        payload = spec.payload()
        rt = spec.runtime(Recorded(spec.script(payload)), spec.sources())

        port = free_port()
        config = uvicorn.Config(api.create_app(rt), host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise TimeoutError("server did not start")

        base = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(base_url=base, timeout=20) as client:
                console = client.get("/")
                health = client.get("/health").json()
                accepted = client.post(
                    "/intake", json={"run_id": "smoke", "entity": "e1", "payload": payload}
                )
                drained = client.post("/drain").json()
                paused = client.get("/runs/smoke").json()
                waiting = client.get("/approvals").json()
                done = client.post("/approvals/smoke/approve").json()
                events = client.get("/events").json()

            return {
                # The port is NOT recorded. It is whatever the OS handed out, so
                # writing it made this artefact differ on every run for a reason
                # that says nothing about the product - and a committed file that
                # cannot reproduce is one nobody can check against the command.
                # `tests/test_product_scripts.py` compares the two now.
                "console_ok": console.status_code == 200
                and "agent console" in console.text
                and "{{" not in console.text,
                "domain": health["domain"],
                "topics": len(health["topics"]),
                "intake": accepted.status_code,
                "handled": drained["handled"],
                "paused_at": paused.get("awaiting"),
                "approvals_listed": len(waiting),
                "final": done["status"],
                "llm_calls": done["llm_calls"],
                "events": len(events),
            }
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    finally:
        for p in paths:
            sys.path.remove(p)


def main() -> int:
    results, bad = {}, 0
    for product in PRODUCTS:
        try:
            r = serve(product)
            ok = (
                r["console_ok"]
                and r["intake"] == 202
                and r["handled"] == 1
                and r["paused_at"] == "approve"
                and r["final"] == "done"
            )
            bad += 0 if ok else 1
            mark = "ok " if ok else "BAD"
            print(
                f"  {mark} {product.name:18} {r['domain']:8} "
                f"console={r['console_ok']} intake={r['intake']} "
                f"paused@{r['paused_at']} -> {r['final']} ({r['llm_calls']} calls)"
            )
            results[product.name] = r
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(f"  BAD {product.name:18} {type(exc).__name__}: {exc}")
            results[product.name] = {"error": f"{type(exc).__name__}: {exc}"}

    (ROOT / "scripts" / "served.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n{len(PRODUCTS) - bad}/{len(PRODUCTS)} products served over HTTP")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
