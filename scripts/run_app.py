"""Open one of the ten measurement apps in a browser.

    python scripts/run_app.py                 # list them
    python scripts/run_app.py 01_localizer    # serve it and open it
    python scripts/run_app.py localizer       # the number is optional
    python scripts/run_app.py 04 --port 8081 --no-open

There was no documented way to start one. The suite imports them with `importlib` and
drives them through a TestClient, `scripts/smoke_serve.py` boots the twenty PRODUCTS, and
the root README explains the measurement scripts - but nothing said how a reader opens
the app itself, and `uvicorn apps.01_localizer.app:app` does not work: a module path
cannot begin with a digit, which is why everything here reaches them through
`import_module` instead.

Each app is a FastAPI application and needs no broker, no database and no model: the bus
and store fall back to in-memory, and the masthead chips say which of them are live. A
run with none of them is the normal one.
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

APPS = sorted(
    p.name
    for p in (ROOT / "apps").iterdir()
    if p.is_dir() and p.name[:2].isdigit() and (p / "app.py").is_file()
)


def resolve(wanted: str) -> str:
    """`01_localizer`, `localizer` or `01` - whichever the reader typed."""
    wanted = wanted.strip().lower()
    exact = [a for a in APPS if a.lower() == wanted]
    if exact:
        return exact[0]
    # By number, or by the name after it.
    matches = [a for a in APPS if a[:2] == wanted.zfill(2) or a[3:].lower() == wanted]
    if not matches:
        matches = [a for a in APPS if wanted in a.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(
            f"no app matches {wanted!r}. One of:\n  " + "\n  ".join(APPS)
        )
    raise SystemExit(f"{wanted!r} matches several: {', '.join(matches)}")


def free_port(preferred: int) -> int:
    """`preferred`, or one the OS picks if it is taken.

    Taken rather than refused, because the common reason is another of these ten already
    running - and telling someone their port is busy is less use than giving them one.
    """
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_app.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("app", nargs="?", help="which app; omit to list them")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="serve without opening a browser")
    args = parser.parse_args(argv)

    if not args.app:
        print(f"{len(APPS)} apps:\n")
        for name in APPS:
            module = importlib.import_module(f"apps.{name}.app")
            theme = getattr(getattr(module, "app", None), "title", "") or name
            print(f"  {name:22} {theme}")
        print("\n  python scripts/run_app.py <name>")
        return 0

    name = resolve(args.app)
    module = importlib.import_module(f"apps.{name}.app")
    app = getattr(module, "app", None)
    if app is None:
        raise SystemExit(f"apps/{name}/app.py defines no `app`")

    try:
        import uvicorn
    except ModuleNotFoundError:
        raise SystemExit(
            "uvicorn is not installed in this environment. It is a dependency of the "
            "apps extra: `uv sync --extra apps`, or `pip install uvicorn`."
        ) from None

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    if port != args.port:
        print(f"  port {args.port} was taken, using {port}")
    print(f"\n  {name}\n  open   : {url}\n  stop   : Ctrl-C\n")
    if not args.no_open:
        # After the server is up, not before: opening first shows a connection error and
        # the reader reloads by hand.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
