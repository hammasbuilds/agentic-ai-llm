"""NiceGUI front end for test-smith.

Run with:  uv run --extra ui python ui/app.py

The point of a UI here is the survivor list. A mutation score is one number and
belongs in a terminal; *which* mutants lived, on which lines, and whether those
lines were executed, is a list you want to click through against the source.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nicegui import ui  # noqa: E402

from testsmith.runner import run, source_files  # noqa: E402

DEFAULT_ROOT = Path(os.environ.get("REPOS_ROOT") or Path.home() / "code").expanduser()

state: dict = {"report": None, "running": False}


def discover_repos(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "tests").is_dir() or (d / "pyproject.toml").exists():
            out.append(d.name)
    return out


@ui.page("/")
def index() -> None:
    ui.colors(primary="#2563eb")

    with ui.header().classes("items-center justify-between"):
        ui.label("test-smith").classes("text-lg font-semibold")
        ui.label("Did the test check the line, or merely run it?").classes(
            "text-sm opacity-70"
        )

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
        with ui.row().classes("w-full items-end gap-3"):
            root_input = ui.input("Checkout folder", value=str(DEFAULT_ROOT)).classes(
                "flex-grow"
            )
            repo_select = ui.select(
                discover_repos(DEFAULT_ROOT), label="Repository"
            ).classes("w-64")
            limit_input = ui.number("Mutant cap", value=40, min=1, max=2000).classes("w-32")
            run_button = ui.button("Run")

        def refresh_repos() -> None:
            repo_select.options = discover_repos(Path(root_input.value))
            repo_select.update()

        root_input.on("blur", lambda _: refresh_repos())

        status = ui.label("").classes("text-sm opacity-70")
        progress = ui.linear_progress(value=0, show_value=False).classes("w-full")
        progress.visible = False

        # -- scoreboard ---------------------------------------------------
        with ui.row().classes("w-full gap-3 flex-wrap") as scores:
            pass
        scores.visible = False

        results_area = ui.column().classes("w-full gap-4")

        def render(report) -> None:
            scores.clear()
            results_area.clear()
            scores.visible = True

            def card(value: str, caption: str, colour: str = "") -> None:
                with scores:
                    with ui.card().classes("p-4 min-w-36"):
                        ui.label(value).classes(f"text-2xl font-semibold {colour}")
                        ui.label(caption).classes("text-xs opacity-60")

            card(f"{report.score:.0%}", "overall score")
            card(
                f"{report.covered_score:.0%}",
                "score on executed lines",
                "text-blue-600",
            )
            card(str(report.killed), "killed")
            card(str(report.survived), "survived", "text-amber-600")
            card(str(report.errored), "excluded (import broke)")

            with results_area:
                on_covered = report.survivors_on_covered_lines
                ui.label("Survivors on lines the suite executed").classes(
                    "text-base font-semibold mt-2"
                )
                ui.label(
                    "A coverage report marks these lines green. The test ran them, "
                    "the code was wrong, and nothing failed."
                ).classes("text-sm opacity-70")

                if not on_covered:
                    ui.label(
                        "None - every executed line that could be mutated was checked."
                    ).classes("text-sm text-green-700")
                else:
                    ui.table(
                        columns=[
                            {"name": "path", "label": "File", "field": "path", "align": "left"},
                            {"name": "line", "label": "Line", "field": "line"},
                            {"name": "op", "label": "Operator", "field": "op", "align": "left"},
                            {"name": "change", "label": "Change", "field": "change", "align": "left"},
                        ],
                        rows=[
                            {
                                "path": r.mutant.path,
                                "line": r.mutant.line,
                                "op": r.mutant.operator,
                                "change": f"{r.mutant.before}  ->  {r.mutant.after}",
                            }
                            for r in on_covered
                        ],
                        row_key="line",
                    ).classes("w-full")

                ui.label(
                    f"{len(report.survivors_on_uncovered_lines)} further survivor(s) sit on "
                    "lines no test ever reached - a coverage gap, not a test-quality one."
                ).classes("text-sm opacity-70 mt-2")

                by_op = report.by_operator
                if by_op:
                    ui.label("By operator").classes("text-base font-semibold mt-4")
                    ui.table(
                        columns=[
                            {"name": "op", "label": "Operator", "field": "op", "align": "left"},
                            {"name": "caught", "label": "Caught", "field": "caught"},
                            {"name": "scored", "label": "Scored", "field": "scored"},
                            {"name": "rate", "label": "Rate", "field": "rate"},
                        ],
                        rows=[
                            {
                                "op": op,
                                "caught": c,
                                "scored": s,
                                "rate": f"{c / s:.0%}" if s else "-",
                            }
                            for op, (c, s) in sorted(
                                by_op.items(), key=lambda kv: -kv[1][1]
                            )
                        ],
                        row_key="op",
                    ).classes("w-full")

        async def do_run() -> None:
            if state["running"]:
                return
            repo = Path(root_input.value) / (repo_select.value or "")
            if not repo.is_dir():
                ui.notify("Pick a repository first", type="warning")
                return

            state["running"] = True
            run_button.disable()
            progress.visible = True
            progress.value = 0
            status.text = f"Counting mutants in {repo.name}..."
            scores.visible = False
            results_area.clear()

            limit = int(limit_input.value or 40)

            def progress_cb(i: int, n: int, mutant, outcome: str) -> None:
                progress.value = i / n
                status.text = f"[{i}/{n}] {outcome}: {mutant.label}"

            try:
                report = await asyncio.to_thread(
                    run, repo, limit, 6.0, 20.0, None, progress_cb
                )
            except RuntimeError as exc:
                ui.notify(str(exc)[:200], type="negative", multi_line=True)
                status.text = "The suite does not pass before mutation - nothing to measure."
                return
            finally:
                state["running"] = False
                run_button.enable()
                progress.visible = False

            state["report"] = report
            status.text = (
                f"{len(report.results)} mutants run against {report.repo} "
                f"(suite baseline {report.baseline_seconds}s)"
            )
            render(report)

        run_button.on_click(do_run)


ui.run(title="test-smith", port=8081, reload=False, show=False)
