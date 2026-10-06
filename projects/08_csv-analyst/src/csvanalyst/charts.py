"""SVG charts written by hand, so the tool stays dependency-free.

Only two marks are needed for a data profile - a histogram for a numeric
column and a horizontal bar for a categorical one - and both are a few dozen
lines of SVG. matplotlib would be forty megabytes to draw a rectangle.

Charts are theme-aware via `currentColor` and a CSS variable, so the same file
is legible embedded in a light or a dark page.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from .profile import is_finite

PALETTE = ("#2563eb", "#0d9488", "#b45309", "#7c3aed", "#be123c")


@dataclass
class Box:
    width: int = 640
    height: int = 260
    left: int = 58
    right: int = 16
    top: int = 16
    bottom: int = 42

    @property
    def plot_w(self) -> int:
        return self.width - self.left - self.right

    @property
    def plot_h(self) -> int:
        return self.height - self.top - self.bottom


def _header(box: Box, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box.width} {box.height}" '
        f'width="100%" role="img" aria-label="{html.escape(title)}" '
        f'style="font-family:ui-sans-serif,system-ui,sans-serif;font-size:11px">',
        "<style>"
        ".axis{stroke:currentColor;opacity:.25}"
        ".tick{fill:currentColor;opacity:.65}"
        ".lbl{fill:currentColor;opacity:.85}"
        "</style>",
    ]


def _nice_number(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:.1f}k"
    if magnitude >= 10:
        return f"{value:.0f}"
    return f"{value:.2f}"


def histogram(values: list[float], title: str, bins: int = 24, box: Box | None = None) -> str:
    """Distribution of a numeric column.

    Bin edges are computed on the raw values including outliers, because
    trimming them is the thing that hides the -53,594 price.

    A non-finite value is not an outlier, though, and this used to raise
    `ValueError: cannot convert float NaN to integer` on one - `inf - inf` is NaN,
    and `int(NaN)` is not a number. It is dropped and the drop is written on the
    chart, because a bar chart missing a value it does not mention is the quiet
    version of the same problem.
    """
    box = box or Box()
    out = _header(box, title)
    usable = [v for v in values if is_finite(v)]
    dropped = len(values) - len(usable)
    if not usable:
        label = "no finite values" if dropped else "no values"
        out.append(f'<text x="12" y="24" class="lbl">{label}</text></svg>')
        return "".join(out)
    values = usable

    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = int((v - lo) / width)
        counts[min(max(idx, 0), bins - 1)] += 1
    peak = max(counts) or 1
    if dropped:
        out.append(
            f'<text x="12" y="{box.top - 4:.0f}" class="lbl">'
            f"{dropped:,} non-finite value(s) not binned</text>"
        )

    bar_w = box.plot_w / bins
    for i, count in enumerate(counts):
        h = (count / peak) * box.plot_h
        x = box.left + i * bar_w
        y = box.top + box.plot_h - h
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bar_w - 1, 0.8):.1f}" '
            f'height="{h:.1f}" fill="{PALETTE[0]}" opacity="0.85">'
            f"<title>{_nice_number(lo + i * width)} to "
            f"{_nice_number(lo + (i + 1) * width)}: {count:,}</title></rect>"
        )

    base = box.top + box.plot_h
    out.append(
        f'<line class="axis" x1="{box.left}" y1="{base}" '
        f'x2="{box.left + box.plot_w}" y2="{base}"/>'
    )
    for frac in (0.0, 0.5, 1.0):
        x = box.left + frac * box.plot_w
        out.append(
            f'<text class="tick" x="{x:.0f}" y="{base + 15}" '
            f'text-anchor="{"start" if frac == 0 else "end" if frac == 1 else "middle"}">'
            f"{_nice_number(lo + frac * (hi - lo))}</text>"
        )
    out.append(f'<text class="tick" x="{box.left}" y="{box.top + 9}">{peak:,}</text>')
    out.append(
        f'<text class="lbl" x="{box.left + box.plot_w / 2}" y="{box.height - 8}" '
        f'text-anchor="middle">{html.escape(title)}</text>'
    )
    out.append("</svg>")
    return "".join(out)


def bars(pairs: list[tuple[str, float]], title: str, box: Box | None = None) -> str:
    """Horizontal bars for a categorical column's top values."""
    box = box or Box(height=max(160, 30 + 22 * max(len(pairs), 1)), left=150)
    out = _header(box, title)
    if not pairs:
        out.append('<text x="12" y="24" class="lbl">no values</text></svg>')
        return "".join(out)

    peak = max(v for _, v in pairs) or 1
    row_h = box.plot_h / len(pairs)
    for i, (label, value) in enumerate(pairs):
        y = box.top + i * row_h
        w = (value / peak) * box.plot_w
        shown = label if len(label) <= 22 else label[:21] + "…"
        out.append(
            f'<text class="lbl" x="{box.left - 8}" y="{y + row_h / 2 + 4:.1f}" '
            f'text-anchor="end">{html.escape(shown)}</text>'
        )
        out.append(
            f'<rect x="{box.left}" y="{y + 3:.1f}" width="{w:.1f}" '
            f'height="{max(row_h - 6, 4):.1f}" rx="2" fill="{PALETTE[1]}" opacity="0.85">'
            f"<title>{html.escape(label)}: {value:,.0f}</title></rect>"
        )
        out.append(
            f'<text class="tick" x="{box.left + w + 6:.1f}" '
            f'y="{y + row_h / 2 + 4:.1f}">{value:,.0f}</text>'
        )
    out.append(
        f'<text class="lbl" x="{box.left + box.plot_w / 2}" y="{box.height - 6}" '
        f'text-anchor="middle">{html.escape(title)}</text>'
    )
    out.append("</svg>")
    return "".join(out)


def sparkline(values: list[float], width: int = 220, height: int = 40) -> str:
    """A bare line, for a date-ordered numeric column.

    The finite filter is applied before the minimum, not inside the comprehension.
    Done after, a single non-finite value made `lo` and `hi` NaN - so every remaining
    coordinate was NaN too and the filter dropped only the one point that caused it,
    leaving a chart that renders as nothing with no error raised.
    """
    values = [v for v in values if is_finite(v)]
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - ((v - lo) / span) * height:.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
        f'<polyline fill="none" stroke="{PALETTE[0]}" stroke-width="1.5" '
        f'points="{points}"/></svg>'
    )
