"""Panel dashboard for log-detective.

    uv run --extra ui panel serve ui/app.py --show

Panel because the interesting output is a curve - compression against what it
destroys - and the threshold wants a slider. The one rule the layout enforces:
the two numbers are always drawn together. Showing the compression ratio alone
is how template extraction gets sold.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import panel as pn  # noqa: E402

from detective.templates import extract, sweep  # noqa: E402

pn.extension(sizing_mode="stretch_width")

DATA = Path(__file__).resolve().parents[1] / "data"


def load(folder: str) -> list[str]:
    path = Path(folder)
    if not path.is_dir():
        return []
    lines: list[str] = []
    for f in sorted(path.glob("*.log")):
        lines += f.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines


folder_input = pn.widgets.TextInput(name="Log folder", value=str(DATA))
threshold = pn.widgets.FloatSlider(
    name="Similarity threshold", start=0.1, end=0.95, step=0.05, value=0.6
)


def scoreboard(folder: str, value: float):
    lines = load(folder)
    if not lines:
        return pn.pane.Alert(f"No .log files in {folder}", alert_type="warning")

    result = extract(lines, threshold=value)
    return pn.Row(
        pn.indicators.Number(
            name="lines", value=result.lines, format="{value:,}", font_size="28pt"
        ),
        pn.indicators.Number(name="templates", value=len(result.templates), font_size="28pt"),
        pn.indicators.Number(
            name="compression",
            value=result.compression,
            format="{value:.1f}x",
            font_size="28pt",
            colors=[(3, "green"), (100, "orange")],
        ),
        pn.indicators.Number(
            name="distinctions lost",
            value=result.distinct_messages_lost,
            font_size="28pt",
            colors=[(0, "green"), (10_000, "red")],
        ),
    )


def cost_table(folder: str):
    lines = load(folder)
    if not lines:
        return pn.pane.Markdown("")
    rows = [
        "| threshold | templates | compression | merged | distinctions lost | singletons |",
        "|---|---|---|---|---|---|",
    ]
    for result in sweep(lines):
        rows.append(
            f"| {result.threshold:.1f} | {len(result.templates)} | "
            f"{result.compression:.1f}x | {len(result.merged_templates)} | "
            f"**{result.distinct_messages_lost}** | {len(result.singletons)} |"
        )
    return pn.pane.Markdown(
        "### What compression costs\n\n"
        + "\n".join(rows)
        + "\n\n*Distinctions lost* counts messages that no longer have a template of "
        "their own. Compression is bought by deciding two lines are the same one."
    )


def merged_table(folder: str, value: float):
    lines = load(folder)
    if not lines:
        return pn.pane.Markdown("")
    result = extract(lines, threshold=value)
    merged = sorted(result.merged_templates, key=lambda t: -t.distinct_messages)[:12]
    if not merged:
        return pn.pane.Alert("Nothing was merged at this threshold.", alert_type="success")

    out = ["### Templates that merged distinct messages", ""]
    for template in merged:
        out.append(f"**{template.distinct_messages} messages** — `{template.text[:90]}`")
        for example in template.examples(2):
            out.append(f"  - was: `{example[:88]}`")
        out.append("")
    return pn.pane.Markdown("\n".join(out))


def rare_table(folder: str, value: float):
    lines = load(folder)
    if not lines:
        return pn.pane.Markdown("")
    result = extract(lines, threshold=value)
    rows = ["### Rarest templates", "", "| count | line | template |", "|---|---|---|"]
    for template in result.rarest(12):
        rows.append(f"| {template.count} | {template.first_line} | `{template.text[:80]}` |")
    return pn.pane.Markdown("\n".join(rows))


pn.template.FastListTemplate(
    title="log-detective",
    sidebar=[
        folder_input,
        threshold,
        pn.pane.Markdown(
            "Template extraction collapses a log into patterns. It does that by "
            "deciding two lines are the same event.\n\n"
            "Sometimes they are not, and the merged-away line is "
            "disproportionately the rare one — the reason you opened the log."
        ),
    ],
    main=[
        pn.bind(scoreboard, folder_input, threshold),
        pn.bind(cost_table, folder_input),
        pn.bind(merged_table, folder_input, threshold),
        pn.bind(rare_table, folder_input, threshold),
    ],
).servable()
