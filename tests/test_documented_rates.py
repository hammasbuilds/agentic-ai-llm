"""Every number an app states, against the run that produced it.

Each app quotes one measured run in three places - the module docstring, the ABOUT
panel the UI renders, and a bullet in the root README - and nothing compared them to
the run or to each other. App 02's three had drifted from all three: the docstring
said "17.6% of 5,116 mutants" and "227 of 782 problems" where the measurement over
the whole split is 18.0% of 4,055 and 326 of 971, and 782 was neither the number of
problems loaded nor the number whose reference passes its own tests - no code
produced it, so nothing could notice.

Re-measuring here is not possible: app 02 alone is about forty minutes of CPU. So
the run's summary counts are committed under `apps/results/` - a few hundred bytes
of integers, not the run artifacts - and the prose is checked against them. An app
with no committed summary is skipped by name, and the number covered is asserted
rather than assumed, because a parametrised test that silently covers one app of ten
is the failure mode this file exists to catch.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPS = sorted(p for p in (ROOT / "apps").iterdir() if p.name[0].isdigit())
RESULTS = ROOT / "apps" / "results"

OF_WITH_PCT = re.compile(r"(?<![\d.])([\d,]+) of ([\d,]+)[^.(%]{0,30}\(([\d.]+)%\)")
OF_PLAIN = re.compile(r"(?<![\d.])([\d,]+) of (?:the )?([\d,]+)(?![\d.%])")


def _n(raw: str) -> int:
    return int(raw.replace(",", ""))


def regions(app: Path) -> dict[str, str]:
    """The module docstring and the ABOUT panel, kept apart.

    Kept apart because joining them hides the thing worth catching. Written as one
    string first, and a deliberate 18.0 -> 18.4 corruption in the ABOUT panel passed:
    the docstring still held the right figure somewhere in the same blob. Each region
    now has to carry the run's numbers on its own.

    Deliberately not the whole file either. A code comment recording a superseded
    number - "the README used to quote 227 of 782" - is the record of the fix, and
    has to survive a check that the superseded number is gone from the prose.
    """
    tree = ast.parse((app / "app.py").read_text(encoding="utf-8"))
    out = {"docstring": ast.get_docstring(tree) or ""}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "ABOUT" for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out["about"] = node.value.value
    return out


def prose(app: Path) -> str:
    """Both regions joined. Only for checks that are about the file as a whole."""
    return chr(10).join(regions(app).values())


def summary(app: Path) -> dict | None:
    path = RESULTS / f"{app.name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def mutation_summary(app: Path) -> dict | None:
    """A committed run of the mutation shape, or None. Shape, not name, selects it."""
    run = summary(app)
    return run if run and "mbpp" in run else None


# -- what holds for every app ---------------------------------------------


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_no_stated_part_exceeds_its_whole(app: Path):
    found = OF_PLAIN.findall(prose(app))
    for part, whole in found:
        assert _n(part) <= _n(whole), f"{app.name}: {part} of {whole}"


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_every_stated_fraction_is_its_own_percentage(app: Path):
    for part, whole, pct in OF_WITH_PCT.findall(prose(app)):
        part, whole, pct = _n(part), _n(whole), float(pct)
        assert part <= whole, f"{app.name}: {part} of {whole}"
        assert abs(part / whole * 100 - pct) < 0.1, f"{app.name}: {part}/{whole} is not {pct}%"


# -- against the committed run --------------------------------------------


def test_the_committed_summaries_cover_the_apps_they_claim_to():
    """Two apps of ten. Asserted, so the figure cannot quietly become zero.

    The other eight state numbers from runs that needed both model sizes on a GPU, so
    there is nothing to check them against here and they are skipped by name rather
    than passed. Eight skips that look like eight passes is the failure this file is
    about, so the count is pinned.
    """
    covered = sorted(p.stem for p in RESULTS.glob("*.json"))
    assert covered == ["02_false_accepts", "03_vuln_baseline"]
    assert {p.name for p in APPS} >= set(covered)


def flat(text: str) -> str:
    """Tag-stripped and whitespace-collapsed, so one region's <b> and the other's
    line wrapping do not make the same sentence look like two different claims."""
    return " ".join(re.sub(r"<[^>]+>", "", text).split())


@pytest.mark.parametrize("region", ["docstring", "about"])
@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_both_regions_state_the_same_headline_figures(app: Path, region: str):
    """Whatever each region says at length, these it has to agree on.

    Checked per region rather than over the two joined, because joined they cover for
    each other: a deliberate 18.0 -> 18.4 corruption in the ABOUT panel passed while
    the docstring still held the right figure in the same blob.
    """
    run = mutation_summary(app)
    if run is None:
        pytest.skip(f"no committed mutation run for {app.name}")
    found = regions(app)
    assert region in found, f"{app.name} has no {region}"
    text = flat(found[region])
    full, san = run["mbpp"], run["mbpp-sanitized"]

    assert f"{full['survival_rate'] * 100:.1f}% of {full['mutants']:,} mutants" in text
    assert f"{full['proven']} of them are provably wrong" in text
    assert f"{san['survival_rate'] * 100:.1f}% of {san['mutants']:,}" in text


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_the_docstring_states_the_population_the_rates_are_over(app: Path):
    run = mutation_summary(app)
    if run is None:
        pytest.skip(f"no committed mutation run for {app.name}")
    text = flat(regions(app)["docstring"])
    full, san = run["mbpp"], run["mbpp-sanitized"]

    # A mutant of a reference that already fails its own tests says nothing, so the
    # rates are over the usable problems and the docstring has to say which those are.
    assert full["problems_usable"] + full["problems_whose_reference_fails"] == full["problems"]
    assert f"{full['problems_usable']} of MBPP's {full['problems']}" in text
    assert f"all {san['problems']} of the sanitized split" in text
    assert (
        f"{full['problems_with_a_survivor']} of the {full['problems_usable']} usable problems"
        in text
    )


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_the_about_panel_breaks_the_run_down_as_the_run_does(app: Path):
    run = mutation_summary(app)
    if run is None:
        pytest.skip(f"no committed mutation run for {app.name}")
    text = flat(regions(app)["about"])
    full, san = run["mbpp"], run["mbpp-sanitized"]

    assert f"{full['proven_share_of_all'] * 100:.1f}% of all mutants" in text
    assert f"{full['proven_share_of_survivors'] * 100:.1f}% of the survivors" in text

    # The unproven are reported rather than counted, and they account for the rest.
    assert full["survived"] - full["proven"] == full["unproven"]
    assert (
        full["unproven_tried_and_not_separated"] + full["unproven_never_tried"]
        == (full["unproven"])
    )
    assert f"The other {full['unproven']} are reported unproven, not counted" in text
    assert (
        f"{full['unproven_tried_and_not_separated']} were hunted without a separating input "
        f"being found and {full['unproven_never_tried']} could not be tried" in text
    )

    rate = full["problems_with_a_survivor"] / full["problems_usable"] * 100
    assert f"{full['problems_with_a_survivor']} of {full['problems_usable']} ({rate:.1f}%)" in text

    # Per-kind survival, in the order the panel ranks them.
    kinds = full["by_kind"]
    assert f"{kinds['const']['rate'] * 100:.1f}% of the time" in text
    assert f"{kinds['compare']['rate'] * 100:.1f}%" in text
    assert f"{kinds['binop']['rate'] * 100:.1f}% for a swapped arithmetic operator" in text
    assert f"{kinds['negate_if']['rate'] * 100:.1f}% for a negated condition" in text
    assert kinds["const"]["rate"] > kinds["compare"]["rate"] > kinds["binop"]["rate"]

    san_rate = san["problems_with_a_survivor"] / san["problems_usable"] * 100
    assert f"{san['problems']} problems the authors hand-verified" in text
    assert f"{san['problems_with_a_survivor']} of them ({san_rate:.1f}%)" in text


def test_the_root_readme_bullet_quotes_the_same_run():
    run = summary(APPS[1])
    assert APPS[1].name == "02_false_accepts"
    full, san = run["mbpp"], run["mbpp-sanitized"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"{full['survival_rate'] * 100:.1f}% of {full['mutants']:,} single-point" in readme
    assert str(full["proven"]) in readme
    assert f"{san['survival_rate'] * 100:.1f}%" in readme


def test_the_superseded_run_is_quoted_nowhere_in_the_prose():
    text = prose(APPS[1]) + (ROOT / "README.md").read_text(encoding="utf-8")
    for gone in ("5,116", "17.6%", "442", " 782", "16.0%", "427 problems", "25.3%"):
        assert gone not in text, f"{gone} is from the superseded run"


# -- app 03, whose claims are dataset facts rather than a model run -------


def test_app_03_quotes_the_devign_split_as_it_is():
    """Four constants, all of them readable from the file without a model.

    They are the reason this app exists: a published accuracy of ~62% is eight points
    over the always-SAFE baseline, and the app's own headline once compared the model
    against the opposite constant. The model's accuracy is deliberately not quoted
    until it is re-measured against the seeded sample, so what is checkable here is
    the baseline, and all of it is.
    """
    app = next(a for a in APPS if a.name == "03_vuln_baseline")
    run = summary(app)
    text = flat(regions(app)["docstring"]) + " " + flat(regions(app)["about"])

    assert run["safe"] + run["vulnerable"] == run["rows"]
    assert f"{run['safe']} safe to {run['vulnerable']} vulnerable" in text
    assert f"{run['always_safe'] * 100:.1f}%" in text
    assert f"{run['first_800_safe_share'] * 100:.1f}% safe" in text
    assert f"{run['seeded_800_safe_share'] * 100:.1f}% safe at 800" in text

    # The point of returning both constants: over the whole split they coincide, and
    # on the front-of-file sample they are opposites. A single `beats_baseline` field
    # hid which one a verdict meant.
    assert run["majority"] == run["always_safe"]
    assert run["first_800_safe_share"] < 0.5 < run["seeded_800_safe_share"]


def test_app_03_still_declines_to_quote_a_model_number():
    """It was measured against the unrepresentative sample, so it is not printed."""
    app = next(a for a in APPS if a.name == "03_vuln_baseline")
    text = flat(regions(app)["docstring"])
    assert "The model's own accuracy is deliberately not quoted here" in text
    assert "Run it to get one" in text
