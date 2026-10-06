"""Serve the Lit UI and its API from the standard library.

    python ui/serve.py            # http://127.0.0.1:8100

Lit is loaded from a CDN as an ES module, so there is no npm and no build
step - the .js file in this directory is the source that runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from auditor.controls import CONTROLS  # noqa: E402
from auditor.report import audit_folder, to_json  # noqa: E402

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/api/audit":
            params = parse_qs(parsed.query)
            raw = (params.get("path") or [""])[0]
            # Required, not defaulted to ".". `/api/audit` with no path audited the
            # package's own source directory and answered with a confident
            # `{"rate": 0.0833}` - a real-looking figure about whatever the server
            # happened to be started in, which a reader has no way to distinguish from
            # a figure about the folder they meant.
            if not raw:
                self._send(
                    json.dumps(
                        {"error": "path is required: /api/audit?path=<folder of checkouts>"}
                    ).encode(),
                    "application/json",
                    400,
                )
                return
            target = Path(raw)
            if not target.is_dir():
                self._send(
                    json.dumps({"error": f"not a directory: {target}"}).encode(),
                    "application/json",
                    400,
                )
                return
            try:
                audit = audit_folder(target)
            except OSError as unreadable:
                # `?path=C:/Windows/Temp` raised PermissionError out of the handler,
                # which closes the socket with no response at all.
                self._send(
                    json.dumps({"error": f"{target} could not be read: {unreadable}"}).encode(),
                    "application/json",
                    400,
                )
                return
            payload = json.loads(to_json(audit))
            payload["policies"] = {c.id: c.policy for c in CONTROLS}
            payload["unmeasured"] = sum(
                1 for repo in audit.repos for r in repo.results if not r.counted
            )
            self._send(json.dumps(payload).encode(), "application/json")
            return

        name = "index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/")
        target = (HERE / name).resolve()
        # Never serve outside this directory.
        if not target.is_file() or HERE not in target.parents:
            self._send(b"not found", "text/plain", 404)
            return
        self._send(target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"))


def main() -> int:
    parser = argparse.ArgumentParser(description="compliance-auditor UI")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"compliance-auditor on http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
