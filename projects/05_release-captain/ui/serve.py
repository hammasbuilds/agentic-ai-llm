"""Web view for release-captain, served by the standard library.

The build plan called for FastAPI here. It is not needed: this serves one HTML
page and two JSON endpoints, which `http.server` does without a dependency.
Alpine.js is loaded from a CDN and is the only thing fetched from the network.

    python ui/serve.py [checkout-folder] [--port 8090]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captain.gate import evaluate  # noqa: E402
from captain.history import NotAGitRepository, is_repository, read_history  # noqa: E402
from captain.risk import Baseline, score_commit  # noqa: E402

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>release-captain</title>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"></script>
<style>
:root{--bg:#fbfbfa;--panel:#fff;--ink:#1a1c1e;--muted:#6b7280;--line:#e5e7eb;
      --go:#15803d;--warn:#b45309;--stop:#b91c1c;--accent:#2563eb;
      --mono:ui-monospace,Consolas,Menlo,monospace}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#0e1013;--panel:#16191d;--ink:#e6e8ea;--muted:#9099a3;--line:#262b31;
  --go:#4ade80;--warn:#fbbf24;--stop:#f87171;--accent:#60a5fa}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.55 ui-sans-serif,system-ui,'Segoe UI',sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding-block:1.5rem 4rem;padding-inline:20px}
h1{font-size:1.15rem;margin:0 0 .25rem}
.sub{color:var(--muted);font-size:.875rem;margin:0 0 1.5rem}
.row{display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;margin-bottom:1.25rem}
select,input,button{font:inherit;padding:.45rem .7rem;border:1px solid var(--line);
  border-radius:8px;background:var(--panel);color:var(--ink)}
button{background:var(--accent);color:#fff;border-color:transparent;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.verdict{font-size:1.5rem;font-weight:650;letter-spacing:-.02em}
.GO{color:var(--go)} .WARN{color:var(--warn)} .NOGO{color:var(--stop)}
table{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:.875rem}
th,td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--line);
  vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.mono{font-family:var(--mono);font-size:.85em}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
   margin:2rem 0 .7rem}
.pill{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.7rem;
  font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.pill.pass{background:color-mix(in srgb,var(--go) 18%,transparent);color:var(--go)}
.pill.warn{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
.pill.block{background:color-mix(in srgb,var(--stop) 18%,transparent);color:var(--stop)}
.tablewrap{overflow-x:auto}
.note{color:var(--muted);font-size:.85rem;margin-top:.6rem}
</style>
</head>
<body>
<div class="wrap" x-data="captain()" x-init="load()">
  <h1>release-captain</h1>
  <p class="sub">Release readiness from diff statistics. Thresholds are relative to each
     repository's own median.</p>

  <div class="row">
    <select x-model="repo">
      <template x-for="r in repos" :key="r"><option x-text="r"></option></template>
    </select>
    <label class="note">last
      <input type="number" x-model.number="since" min="1" max="200" style="width:5rem">
      commits</label>
    <button @click="check()" :disabled="busy" x-text="busy?'Checking...':'Check'"></button>
    <span class="verdict" :class="cls" x-text="result ? result.verdict : ''"></span>
  </div>

  <template x-if="result">
    <div>
      <h2>Checks</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>Status</th><th>Check</th><th>What it saw</th></tr></thead>
        <tbody>
          <template x-for="c in result.checks" :key="c.name">
            <tr>
              <td><span class="pill" :class="c.status" x-text="c.status"></span></td>
              <td x-text="c.name"></td>
              <td x-text="c.detail"></td>
            </tr>
          </template>
        </tbody>
      </table></div>

      <h2>Riskiest commits</h2>
      <div class="tablewrap"><table>
        <thead><tr><th class="num">Risk</th><th>Commit</th><th class="num">Lines</th>
          <th class="num">Files</th><th class="num">Areas</th><th>Tests</th></tr></thead>
        <tbody>
          <template x-for="c in result.riskiest" :key="c.sha">
            <tr>
              <td class="num" x-text="c.score.toFixed(1)"></td>
              <td><span class="mono" x-text="c.sha.slice(0,8)"></span>
                  <span x-text="' ' + c.subject"></span></td>
              <td class="num" x-text="c.churn.toLocaleString()"></td>
              <td class="num" x-text="c.files"></td>
              <td class="num" x-text="c.spread"></td>
              <td x-text="c.touches_tests ? 'yes' : 'no'"
                  :style="c.touches_tests ? '' : 'color:var(--stop)'"></td>
            </tr>
          </template>
        </tbody>
      </table></div>
      <p class="note">Risk combines breadth, file count, untested source, volume and net
        deletion. Lines alone ranks a regenerated data file above a 693-file refactor.</p>
    </div>
  </template>
</div>

<script>
function captain(){return{
  repos:[], repo:'', since:8, result:null, busy:false,
  get cls(){ if(!this.result) return '';
    return this.result.verdict==='NO-GO'?'NOGO':
           this.result.verdict==='GO'?'GO':'WARN'; },
  async load(){
    const r = await fetch('/api/repos'); this.repos = await r.json();
    if(this.repos.length) this.repo = this.repos[0];
  },
  async check(){
    if(!this.repo) return;
    this.busy = true; this.result = null;
    try{
      const q = `repo=${encodeURIComponent(this.repo)}&since=${this.since}`;
      const r = await fetch(`/api/gate?${q}`);
      this.result = await r.json();
    } finally { this.busy = false; }
  }
}}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    root: Path = Path.cwd()

    def log_message(self, *args) -> None:  # quieter console
        pass

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload).encode("utf-8"), "application/json", status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if parsed.path == "/api/repos":
            names = [
                d.name for d in sorted(self.root.iterdir()) if d.is_dir() and is_repository(d)
            ]
            self._json(names)
            return

        if parsed.path == "/api/gate":
            params = parse_qs(parsed.query)
            name = (params.get("repo") or [""])[0]
            since = int((params.get("since") or ["8"])[0])
            target = self.root / name
            if not name or not is_repository(target):
                self._json({"error": "unknown repository"}, 404)
                return
            try:
                history = read_history(target)
            except NotAGitRepository as exc:
                self._json({"error": str(exc)}, 400)
                return
            result = evaluate(history, since=since)
            baseline = Baseline.from_history(history)
            self._json(
                {
                    "repo": result.repo,
                    "verdict": result.verdict,
                    "blocked": result.blocked,
                    "checks": [
                        {"name": c.name, "status": c.status, "detail": c.detail}
                        for c in result.checks
                    ],
                    "riskiest": [
                        {
                            "sha": c.sha,
                            "subject": c.subject,
                            "score": score_commit(c, baseline).score(),
                            "churn": c.churn,
                            "files": len(c.files),
                            "spread": c.spread,
                            "touches_tests": c.touches_tests,
                        }
                        for c, _ in result.riskiest
                    ],
                }
            )
            return

        self._send(b"not found", "text/plain", 404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Web view for release-captain")
    default_root = Path(os.environ.get("REPOS_ROOT") or Path.home() / "code").expanduser()
    parser.add_argument(
        "folder", nargs="?", default=str(default_root), help="folder containing git checkouts"
    )
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    Handler.root = Path(args.folder).resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"release-captain on http://127.0.0.1:{args.port}  (serving {Handler.root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
