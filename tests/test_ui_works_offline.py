"""No page in this repository fetches anything from the internet to render itself.

The root README tells a reader to run the measurements with "no model and no network",
and that was true of the measurement scripts. The web UI - the part a reader actually
opens - was a different story. `apps/_platform/templates/base.html`, which all ten apps
extend, loaded three things on every page view:

    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter...">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.4/htmx.min.js">

The fonts degraded gracefully: every stack in `themes.py` already names a system face
after the hosted one. **htmx did not.** It was used for exactly one attribute pair, in
`job.html`, and that pair is what puts an app's RESULT on the page:

    <div id="result" hx-get="/job/{id}/result" hx-trigger="load once, resultready from:body">

With the CDN unreachable the app still started, still ran its job, still streamed its
progress over SSE - all of that is vanilla JS - and then showed nothing at all. The one
thing on the page that could not be done without the network was the thing that showed
the answer.

A hyperlink is not a fetch. `<a href="https://github.com/...">` in the footer is fine and
is what the `ANCHOR` exemption below is for: the test is about what the browser loads
before the reader sees the page, not about where the page points.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Every HTML page this repository serves, wherever it lives.
#:
#: Globbed as `**/*.html` rather than `templates/*.html`. The first version used the
#: narrower pattern and passed while `products/platform/src/agentplatform/web/console.html`
#: - the one page all twenty products serve - was loading three fonts from
#: fonts.googleapis.com and carrying no favicon at all. A checker that looks only where
#: the defect was already fixed is the shape of bug this repository keeps finding.
TEMPLATES = sorted(
    p
    for p in ROOT.rglob("*.html")
    if not {".venv", "node_modules", "build", "dist", "htmlcov", ".git"} & set(p.parts)
)

#: Attributes whose value the browser FETCHES. `href` is in here because `<link href>`
#: is a fetch - and left out for `<a>`, which is the whole distinction.
_FETCHING = re.compile(
    r"""(?:src|srcset|data-src|poster|action|formaction)\s*=\s*["']([^"']+)["']"""
    r"""|<link\b[^>]*?href\s*=\s*["']([^"']+)["']"""
    r"""|@import\s+(?:url\()?["']([^"']+)["']""",
    re.I | re.S,
)

#: A scheme-bearing or protocol-relative URL: anything the browser resolves off-machine.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)


def _external_fetches(text: str) -> list[str]:
    found = []
    for match in _FETCHING.finditer(text):
        url = next(g for g in match.groups() if g is not None)
        url = url.strip()
        # `data:` is the page carrying its own bytes, which is the opposite of a fetch.
        if url.lower().startswith("data:"):
            continue
        if _EXTERNAL.match(url):
            found.append(url)
    return found


def test_there_are_templates_to_check():
    """A sweep over an empty list passes, and this repository has more than a few."""
    assert len(TEMPLATES) >= 15, [str(p.relative_to(ROOT)) for p in TEMPLATES]


def test_the_sweep_reaches_the_page_all_twenty_products_serve():
    """Named, because it is the page the first version of this file did not look at.

    It is not under a `templates/` directory - it sits beside the module that reads it -
    so the narrower glob missed it, and it was the worst offender: three font requests
    and no favicon, served by every product.
    """
    console = ROOT / "products" / "platform" / "src" / "agentplatform" / "web" / "console.html"
    assert console.is_file(), console
    assert console in TEMPLATES, "the console is not in the swept set"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_template_loads_anything_off_this_machine(template: Path):
    external = _external_fetches(template.read_text(encoding="utf-8"))
    assert external == [], (
        f"{template.relative_to(ROOT)} fetches {external} to render. The README tells a "
        "reader to run this with no network; a page that waits on a CDN to show its "
        "result does not."
    )


def test_an_anchor_to_the_internet_is_still_allowed():
    """The rule is about what the browser LOADS, not where the page points - and the
    footer links to the repository, which is correct and must not fail this file."""
    assert _external_fetches('<a href="https://github.com/x/y">y</a>') == []
    assert _external_fetches('<link rel="stylesheet" href="https://cdn/x.css">') == [
        "https://cdn/x.css"
    ]
    assert _external_fetches('<script src="//cdn/x.js"></script>') == ["//cdn/x.js"]


def test_the_result_panel_does_not_need_a_library():
    """The specific regression: htmx fetched the result, from a CDN, for one div.

    Checked as behaviour rather than as absence - that the page carries its own fetch
    and its own listener for the event the SSE stream fires.
    """
    job = (ROOT / "apps" / "_platform" / "templates" / "job.html").read_text(encoding="utf-8")

    # Comments stripped first. The replacement explains what it replaced, so the words
    # `hx-get` and `hx-trigger` appear in the file as prose - and the first version of
    # this test read them as markup and failed on its own explanation.
    code = re.sub(r"\{#.*?#\}", "", job, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "hx-get=" not in code and "hx-trigger=" not in code, "htmx is back in job.html"
    assert "fetch('/job/" in job, "nothing fetches the result"
    assert "addEventListener('resultready'" in job, "nothing listens for the done event"
    # And the event is still fired, or the listener above never runs.
    assert "dispatchEvent(new Event('resultready'))" in job


def test_every_font_stack_names_a_face_this_machine_has():
    """Dropping the webfont links is only safe because the fallbacks were already there.

    Each stack must end in a generic family, so a machine with none of the named faces
    still gets the right KIND of type rather than the browser's default serif.
    """
    import sys

    sys.path.insert(0, str(ROOT))
    from apps._platform.themes import THEMES

    generics = ("sans-serif", "serif", "monospace", "system-ui", "ui-monospace")
    for slug, theme in THEMES.items():
        for label, stack in (
            ("display", theme.font_display),
            ("body", theme.font_body),
            ("mono", theme.font_mono),
        ):
            assert any(stack.rstrip().endswith(g) for g in generics), (slug, label, stack)


def test_every_theme_draws_its_own_favicon():
    """It was one emoji in an SVG `<text>`, shared by all ten: a glyph from the OS emoji
    font, at that font's size and colour, and blank where a browser declines to
    rasterise emoji into a favicon."""
    import sys

    sys.path.insert(0, str(ROOT))
    from apps._platform.themes import THEMES

    seen = {}
    for slug, theme in THEMES.items():
        icon = theme.favicon()
        assert icon.startswith("data:image/svg+xml,"), slug
        assert theme.accent.lstrip("#") in icon, (slug, "the accent is not in the mark")
        assert "text-anchor" in icon, slug
        seen[slug] = icon
    # Ten identities, ten marks: an icon shared by two apps is the defect this replaced.
    assert len(set(seen.values())) == len(seen), "two themes render the same favicon"
