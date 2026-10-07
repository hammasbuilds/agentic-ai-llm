"""Capture the operator console from a running product, light and dark.

Real captures of the real page, served by a real server — never a mockup. The
console is shared, so one product is enough to show it; the run it photographs
is a genuine intake -> drain cycle, paused on a real approval.

    python scripts/screenshots.py            # 01_revenue-desk
    python scripts/screenshots.py 12_powerguard
"""

from __future__ import annotations

import importlib
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from product_spec import spec_for  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"

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


def _chromium() -> str | None:
    """The full Chromium, rather than the headless-shell build.

    Playwright prefers a separate `chromium_headless_shell-*` download. On a
    throttled connection that is another 50 MB for a binary that does the same
    job here, so use the full browser if it is already present.
    """
    import os

    root = Path(os.path.expanduser("~/AppData/Local/ms-playwright"))
    found = sorted(root.glob("chromium-*/chrome-win64/chrome.exe"))
    return str(found[-1]) if found else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(dirname: str = "01_revenue-desk") -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: uv pip install playwright")
        print("then: python -m playwright install chromium")
        return 1

    import uvicorn

    product = ROOT / dirname
    paths = [str(product / "src"), str(ROOT / "platform" / "src"), str(product / "tests")]
    for p in paths:
        sys.path.insert(0, p)
    for mod in list(sys.modules):
        if mod.startswith(("test_graph", "agentplatform")) or mod in PKGS:
            del sys.modules[mod]

    tg = importlib.import_module("test_graph")
    from agentplatform import api
    from agentplatform.llm import Recorded

    # Same adapter as `capture.py` and `smoke_serve.py`. This read `tg.payload()`,
    # so the documented `python scripts/screenshots.py 12_powerguard` could not work
    # for any product but `01`.
    spec = spec_for(tg)
    payload = spec.payload()
    rt = spec.runtime(Recorded(spec.script(payload)), spec.sources())

    # Give the console something real to show: one run paused on an approval and
    # one already finished.
    rt.submit("run_1", "e1", payload)
    rt.drain()
    rt.submit("run_2", "e2", payload)
    rt.drain()
    rt.approve("run_2")

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(api.create_app(rt), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)

    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=_chromium())
            for theme, width, height, name in (
                ("light", 1440, 1000, "console-light"),
                ("dark", 1440, 1000, "console-dark"),
                ("light", 390, 844, "console-phone"),
            ):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
                page.wait_for_timeout(2500)  # let the 2s poll populate the panels
                out = SHOTS / f"{name}.png"
                page.screenshot(path=str(out), full_page=True)
                print(f"  {out.relative_to(ROOT)}  {width}x{height} {theme}")
                page.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for p in paths:
            sys.path.remove(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "01_revenue-desk"))
