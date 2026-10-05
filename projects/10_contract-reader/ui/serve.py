"""Serve the contract-reader UI from the standard library.

    python ui/serve.py        # http://127.0.0.1:8115

The build plan said React + Vite. That would mean `npm install` and a bundler
to render three tables, so this is one HTML file with no framework and no
build step - it runs the moment the repository is cloned. The deviation is
deliberate and recorded in the README.
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

from contractreader.cli import _read_all  # noqa: E402
from contractreader.obligations import conflicts  # noqa: E402


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

        if parsed.path == "/api/survey":
            params = parse_qs(parsed.query)
            root = Path((params.get("path") or ["."])[0])
            project = (params.get("project") or ["MIT"])[0]
            if not root.exists():
                self._send(
                    json.dumps({"error": f"no such path: {root}"}).encode(),
                    "application/json",
                    400,
                )
                return

            readings = _read_all(root.resolve())
            families: dict[str, int] = {}
            for reading in readings:
                families[reading.family] = families.get(reading.family, 0) + 1

            self._send(
                json.dumps(
                    {
                        "licences": len(readings),
                        "project": project,
                        "families": families,
                        "rejected_matches": sum(len(r.rejected) for r in readings),
                        "files": [
                            {
                                "path": r.path,
                                "family": r.family,
                                "copyleft": r.copyleft,
                                "obligations": sorted(r.obligations),
                                "conflict": conflicts(project, r),
                            }
                            for r in readings
                        ],
                    }
                ).encode(),
                "application/json",
            )
            return

        name = "index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/")
        target = (HERE / name).resolve()
        if not target.is_file() or HERE not in target.parents:
            self._send(b"not found", "text/plain", 404)
            return
        self._send(target.read_bytes(), "text/html; charset=utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="contract-reader UI")
    parser.add_argument("--port", type=int, default=8115)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"contract-reader on http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
