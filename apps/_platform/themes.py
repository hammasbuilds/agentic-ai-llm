"""Ten visual identities, one per app.

Each app gets its own palette, typeface pairing and surface treatment, so that opening
two of them side by side does not feel like opening the same tool twice. The differences
are not decorative: a forensic tool and a thermal sweep want different reading postures,
and the colour carries that.

Every theme defines the same token names, so the shared layout never asks which app it is
rendering. Dark and light are both represented - four of the ten are light, because a tool
you read tables in is not a tool you watch a live log in.

Contrast was checked for body text against its own surface; the accent colours are used for
fills and borders, not for small text on a coloured ground.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    slug: str
    name: str
    tagline: str
    mode: str  # "dark" | "light"

    bg: str  # page background
    surface: str  # cards, panels
    surface_2: str  # nested / striped rows
    border: str
    text: str
    muted: str
    accent: str  # primary action + focus
    accent_2: str  # secondary series
    good: str
    bad: str
    warn: str

    font_display: str
    font_body: str
    font_mono: str
    radius: str = "10px"
    # A single decorative gradient used on the masthead only.
    glow: str = ""
    extras: dict = field(default_factory=dict)

    def mark(self) -> str:
        """The same mark as `favicon()`, inline, for the masthead.

        The heading was `{{ icon }} {{ theme.name }}` - an emoji before the title. An
        emoji in an <h1> is a glyph from the operating system's emoji font: a different
        shape on Windows, macOS and Linux, a different weight from the type beside it,
        and nothing a palette can tune. The drawn mark is the app's own two colours and
        sits at the cap height of the word next to it.
        """
        letter = (self.name.strip() or "?")[0].upper()
        return (
            "<svg class='mark' viewBox='0 0 32 32' aria-hidden='true' focusable='false'>"
            f"<rect width='32' height='32' rx='7' fill='{self.accent}'/>"
            f"<text x='16' y='22' text-anchor='middle' fill='{self.bg}' "
            "font-family='system-ui,sans-serif' font-size='18' font-weight='700'>"
            f"{letter}</text></svg>"
        )

    def favicon(self) -> str:
        """A data-URI favicon drawn from this theme's own palette.

        This was an emoji inside an SVG `<text>` element, which is not a mark: it is a
        glyph from whatever emoji font the operating system ships, drawn at that font's
        idea of the size and colour, and absent in the browsers that decline to
        rasterise emoji into a favicon at all. Ten apps with ten identities shared one
        rendering accident.

        A rounded square in the accent colour with the app's initial knocked out of it,
        so the tab carries the same identity the page does. SVG rather than a generated
        .ico because it is a few hundred bytes, scales to every size a browser asks for,
        and adds no binary to a repository of text.
        """
        letter = (self.name.strip() or "?")[0].upper()
        # The glyph is cut from the plate in the page background, so it reads on both
        # the light and the dark themes without a second colour decision.
        return (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
            f"%3Crect width='32' height='32' rx='7' fill='{self.accent}'/%3E"
            f"%3Ctext x='16' y='22' text-anchor='middle' fill='{self.bg}' "
            "font-family='system-ui,sans-serif' font-size='18' font-weight='700'%3E"
            f"{letter}%3C/text%3E%3C/svg%3E"
        )

    def css_vars(self) -> str:
        return "\n".join(
            f"      --{k.replace('_', '-')}: {v};"
            for k, v in [
                ("bg", self.bg),
                ("surface", self.surface),
                ("surface-2", self.surface_2),
                ("border", self.border),
                ("text", self.text),
                ("muted", self.muted),
                ("accent", self.accent),
                ("accent-2", self.accent_2),
                ("good", self.good),
                ("bad", self.bad),
                ("warn", self.warn),
                ("font-display", self.font_display),
                ("font-body", self.font_body),
                ("font-mono", self.font_mono),
                ("radius", self.radius),
                ("glow", self.glow or "transparent"),
            ]
        )


_MONO = "'JetBrains Mono', 'SF Mono', ui-monospace, 'Cascadia Code', Consolas, monospace"
_SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
_SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"

THEMES: dict[str, Theme] = {
    # 1 - deep ocean. Retrieval over a codebase: navy, cyan, heavy monospace.
    "localizer": Theme(
        slug="localizer",
        name="Localizer",
        mode="dark",
        tagline="Which file does this issue touch?",
        bg="#07111f",
        surface="#0d1c30",
        surface_2="#122740",
        border="#1d3a55",
        text="#dcebff",
        muted="#7d9cc0",
        accent="#35d6f5",
        accent_2="#7b8cff",
        good="#3ddc97",
        bad="#ff6b6b",
        warn="#ffc857",
        font_display=_MONO,
        font_body=_SANS,
        font_mono=_MONO,
        glow="linear-gradient(135deg, #35d6f5 0%, #7b8cff 100%)",
    ),
    # 2 - crimson lab. Forensics on a benchmark: charcoal and blood red.
    "false-accepts": Theme(
        slug="false-accepts",
        name="False Accepts",
        mode="dark",
        tagline="How much wrong code do three asserts let through?",
        bg="#140a0c",
        surface="#1e1114",
        surface_2="#2a181c",
        border="#3d2228",
        text="#f5e2e4",
        muted="#b08a90",
        accent="#ff4d5e",
        accent_2="#ff9f6b",
        good="#5ed39e",
        bad="#ff4d5e",
        warn="#ffb340",
        font_display=_SERIF,
        font_body=_SANS,
        font_mono=_MONO,
        glow="linear-gradient(135deg, #ff4d5e 0%, #7a1020 100%)",
    ),
    # 3 - amber terminal. Security triage, deliberately CRT.
    "vuln-baseline": Theme(
        slug="vuln-baseline",
        name="Vuln Baseline",
        mode="dark",
        tagline="Can a model beat answering 'safe' every time?",
        bg="#0a0a06",
        surface="#13130c",
        surface_2="#1c1c11",
        border="#2f2f1c",
        text="#ffd98a",
        muted="#a8914f",
        accent="#ffb000",
        accent_2="#8bd450",
        good="#8bd450",
        bad="#ff5f56",
        warn="#ffb000",
        font_display=_MONO,
        font_body=_MONO,
        font_mono=_MONO,
        radius="3px",
        glow="linear-gradient(135deg, #ffb000 0%, #5a3d00 100%)",
    ),
    # 4 - violet gradient. Two model sizes compared: chart-forward.
    "size-curve": Theme(
        slug="size-curve",
        name="Size Curve",
        mode="dark",
        tagline="Where does a 5x bigger model actually pay?",
        bg="#0e0a1c",
        surface="#171130",
        surface_2="#211943",
        border="#31265e",
        text="#e9e3ff",
        muted="#9b8fce",
        accent="#a78bfa",
        accent_2="#22d3ee",
        good="#4ade80",
        bad="#fb7185",
        warn="#fbbf24",
        font_display=_SANS,
        font_body=_SANS,
        font_mono=_MONO,
        radius="14px",
        glow="linear-gradient(135deg, #a78bfa 0%, #22d3ee 100%)",
    ),
    # 5 - forest. A convergence curve: green, calm, lots of whitespace.
    "debug-ceiling": Theme(
        slug="debug-ceiling",
        name="Debug Ceiling",
        mode="light",
        tagline="How many rounds of self-debugging are worth paying for?",
        bg="#f4f7f2",
        surface="#ffffff",
        surface_2="#eaf1e6",
        border="#cfdcc7",
        text="#16241a",
        muted="#5d7061",
        accent="#2f855a",
        accent_2="#84cc16",
        good="#2f855a",
        bad="#c53030",
        warn="#b7791f",
        font_display=_SERIF,
        font_body=_SANS,
        font_mono=_MONO,
        radius="8px",
        glow="linear-gradient(135deg, #2f855a 0%, #84cc16 100%)",
    ),
    # 6 - magenta punch. Mutation testing: loud, because the result is loud.
    "kill-rate": Theme(
        slug="kill-rate",
        name="Kill Rate",
        mode="dark",
        tagline="Do model-written tests catch anything?",
        bg="#10061a",
        surface="#1b0c2b",
        surface_2="#26123c",
        border="#3a1c59",
        text="#fbe9ff",
        muted="#b085cc",
        accent="#e879f9",
        accent_2="#38bdf8",
        good="#34d399",
        bad="#f43f5e",
        warn="#facc15",
        font_display=_SANS,
        font_body=_SANS,
        font_mono=_MONO,
        radius="16px",
        glow="linear-gradient(135deg, #e879f9 0%, #38bdf8 100%)",
    ),
    # 7 - slate and coral. A two-way comparison wants a neutral ground.
    "repair-rewrite": Theme(
        slug="repair-rewrite",
        name="Repair or Rewrite",
        mode="light",
        tagline="Patch the failure, or throw it away?",
        bg="#f6f7f9",
        surface="#ffffff",
        surface_2="#eef1f5",
        border="#d5dae2",
        text="#1b2330",
        muted="#64748b",
        accent="#ef6461",
        accent_2="#3b82f6",
        good="#059669",
        bad="#dc2626",
        warn="#d97706",
        font_display=_SANS,
        font_body=_SANS,
        font_mono=_MONO,
        radius="6px",
        glow="linear-gradient(135deg, #ef6461 0%, #3b82f6 100%)",
    ),
    # 8 - teal paper. Reading five phrasings side by side: editorial, light.
    "prompt-shapes": Theme(
        slug="prompt-shapes",
        name="Prompt Shapes",
        mode="light",
        tagline="How much of a benchmark score is the wording?",
        bg="#fbfaf7",
        surface="#ffffff",
        surface_2="#f0f4f3",
        border="#d8e0de",
        text="#12211f",
        muted="#5b716e",
        accent="#0f766e",
        accent_2="#b45309",
        good="#0f766e",
        bad="#b91c1c",
        warn="#b45309",
        font_display=_SERIF,
        font_body=_SERIF,
        font_mono=_MONO,
        radius="4px",
        glow="linear-gradient(135deg, #0f766e 0%, #b45309 100%)",
    ),
    # 9 - heat. A temperature sweep should look like one.
    "temperature": Theme(
        slug="temperature",
        name="Temperature Lab",
        mode="dark",
        tagline="Where do the pass@1 and pass@k optima diverge?",
        bg="#120705",
        surface="#1e0d09",
        surface_2="#2b130d",
        border="#451e14",
        text="#ffe8dd",
        muted="#c2907c",
        accent="#ff7a18",
        accent_2="#ffd21f",
        good="#6ee7b7",
        bad="#ff4d4d",
        warn="#ffd21f",
        font_display=_SANS,
        font_body=_SANS,
        font_mono=_MONO,
        radius="12px",
        glow="linear-gradient(135deg, #ffd21f 0%, #ff7a18 55%, #cf1512 100%)",
    ),
    # 10 - sepia. Code to prose and back: a manuscript, not a dashboard.
    "roundtrip": Theme(
        slug="roundtrip",
        name="Roundtrip",
        mode="light",
        tagline="What survives code -> prose -> code?",
        bg="#f7f2e9",
        surface="#fffdf8",
        surface_2="#efe6d6",
        border="#ddd0ba",
        text="#2c2418",
        muted="#7a6a52",
        accent="#9a6b3f",
        accent_2="#3f6f8a",
        good="#4f7942",
        bad="#a4402f",
        warn="#b8860b",
        font_display=_SERIF,
        font_body=_SERIF,
        font_mono=_MONO,
        radius="2px",
        glow="linear-gradient(135deg, #9a6b3f 0%, #d8c39c 100%)",
    ),
}


def get(slug: str) -> Theme:
    if slug not in THEMES:
        raise KeyError(f"unknown theme {slug!r}; have {sorted(THEMES)}")
    return THEMES[slug]


def all_themes() -> list[Theme]:
    return list(THEMES.values())
