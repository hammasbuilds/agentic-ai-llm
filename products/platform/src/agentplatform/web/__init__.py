"""The operator console every product serves.

One page, no build step, no npm, no framework. It is the same four things for
all twenty products because they all expose the same Runtime: start work, watch
it, approve what it paused on, read the audit trail.

Deliberately one shared page rather than twenty frontends. Twenty
half-implemented dashboards is the mistake this portfolio already made once and
corrected by deleting them.
"""

from pathlib import Path

CONSOLE = Path(__file__).with_name("console.html")


def html(domain: str) -> str:
    """The console, with the product's domain and its initial baked in.

    The initial is for the favicon. Twenty products served one page with no `<link
    rel="icon">` at all, so every console tab showed the browser's blank-document glyph
    and four of them open at once were indistinguishable.
    """
    initial = (domain.strip() or "?")[0].upper()
    # Escaped, because it lands inside an SVG data URI in an attribute. A domain is a
    # product name from this repository rather than user input, and the escape is here
    # so that stays true of the next one.
    initial = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}.get(
        initial, initial
    )
    return (
        CONSOLE.read_text(encoding="utf-8")
        .replace("{{DOMAIN}}", domain)
        .replace("{{INITIAL}}", initial)
    )
