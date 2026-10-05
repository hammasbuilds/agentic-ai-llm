"""API for the Remix UI, served by the standard library.

    python ui/server.py      # then, in ui/: npm install && npm run dev

Read-only. It returns confirmed *and* retracted verdicts in one payload, so
the UI can show both without a second request - the retraction list is not an
optional extra here.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reviewbot.cli import _python_files  # noqa: E402
from reviewbot.review import Review, review_source  # noqa: E402
from reviewbot.verify import FileContext  # noqa: E402

MAX_FILES = 3000


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/scan":
            self._json({"error": "not found"}, 404)
            return

        params = parse_qs(parsed.query)
        target = Path((params.get("path") or ["."])[0]).resolve()
        include_tests = (params.get("tests") or ["0"])[0] == "1"
        if not target.exists():
            self._json({"error": f"no such path: {target}"}, 400)
            return

        review = Review()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            for path in _python_files(target)[:MAX_FILES]:
                try:
                    source = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if not include_tests and FileContext.build(str(path), source).is_test:
                    continue
                try:
                    shown = str(path.relative_to(target))
                except ValueError:
                    shown = str(path)
                file_review = review_source(shown, source)
                if file_review.verdicts:
                    review.files.append(file_review)

        self._json(
            {
                "proposed": review.proposed,
                "confirmed": review.confirmed,
                "retracted": review.retracted,
                "retraction_rate": round(review.retraction_rate, 4),
                "by_rule": {
                    k: {"proposed": p, "confirmed": c} for k, (p, c) in review.by_rule().items()
                },
                "files": [
                    {
                        "path": f.path,
                        "verdicts": [
                            {
                                "rule": v.rule,
                                "line": v.proposal.line,
                                "confirmed": v.confirmed,
                                "message": v.proposal.message,
                                "severity": v.proposal.severity,
                                "reason": v.reason,
                            }
                            for v in f.verdicts
                        ],
                    }
                    for f in review.files[:200]
                ],
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="review-bot API for the Remix UI")
    parser.add_argument("--port", type=int, default=8110)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"review-bot API on http://127.0.0.1:{args.port}")
    print("now run:  cd ui && npm install && npm run dev")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
