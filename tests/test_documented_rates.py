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

That leaves eight apps whose figures are checked for existence and not for value, and
this file used to cover them with a table of COUNTS - the number of distinct figures
per app - describing itself as "every number in every app's prose is pinned by count,
so changing one is a deliberate edit to this table". The inference is wrong: a value
changes without the count moving. An independent review rewrote `93.3% survived` to
`99.9% survived` in app 05 and the whole suite stayed green, and 56 of the 106 figures
had no value-level protection at all.

The figure SET is frozen instead, in `tests/fixtures/app_figures.json`. A changed value
is one figure appearing and one vanishing, and the failure names both. It is still
weaker than the arithmetic checks on apps 02 and 03 - it says a number was edited on
purpose, not that it is right - and that difference is what the coverage test below
prints rather than leaves to be assumed.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
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

    # The `hint=` on every Field, which is the prose a visitor who never reads the
    # source actually sees - it is rendered beside the input they fill in. It was
    # outside every check here, and app 02's hint was still quoting a figure this
    # module's own list of superseded numbers named as gone. The suite was green
    # because these three regions were two.
    hints = [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Field"
        for keyword in node.keywords
        if keyword.arg == "hint"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    ]
    if hints:
        out["hints"] = chr(10).join(hints)
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


#: Every figure each app's prose states, as the count of distinct numbers in it.
#:
#: This exists because the two arithmetic checks below cover almost nothing. They
#: match the shape "N of M (P%)", which only app 02 writes: over the other nine the
#: `for` body never executes and the test reports a pass having asserted nothing. An
#: independent review counted it — 18 of 20 reported passes were empty — and this
#: file's own docstring had already named that failure mode as the thing it exists to
#: catch, which is the second time the same mistake has been made in the same file.
#:
#: Generic regex arithmetic over free prose is the wrong instrument: the apps state
#: figures as "of the 198 tasks either size can solve, the 3B already handles 75.8%",
#: and no reasonable pattern pairs those up. So the guarantee here is weaker and
#: Where every distinct figure in every app's prose is frozen. This was a table of
#: COUNTS in this file - `{"05_debug_ceiling": 11}` - and the docstring above claimed
#: "every number in every app's prose is pinned by count, so changing one is a
#: deliberate edit to this table". That does not follow: a value can change without
#: the count moving. An independent review rewrote `93.3% survived` to `99.9%` and all
#: 470 tests passed. Only apps 02 and 03 have a committed run to check values against,
#: so 56 of the 106 figures had no value-level protection at all.
#:
#: The set is pinned now, so a changed value is one figure appearing and one vanishing,
#: and the failure message names both. `python scripts/freeze_app_figures.py` re-freezes
#: it once the new number has been checked.
FIGURES = ROOT / "tests" / "fixtures" / "app_figures.json"


def frozen() -> dict[str, dict[str, int]]:
    """Each app's figures and HOW MANY TIMES each is stated.

    A multiset, because the two simpler shapes were each the defect in turn. A table of
    counts - `{"05_debug_ceiling": 11}` - let a value change while the count stayed 11.
    A set let a value change into one already in the set, and every app quotes the same
    run in three regions, so most of its figures appear more than once: rewriting one
    `76.0` to `75.8` in app 04's ABOUT panel moved neither the size nor the membership.
    """
    assert FIGURES.is_file(), f"{FIGURES.name} is missing; run scripts/freeze_app_figures.py"
    held = json.loads(FIGURES.read_text(encoding="utf-8"))["apps"]
    return {app: dict(counts) for app, counts in held.items()}


NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)%?(?![\w])")


def figures(app: Path) -> dict[str, int]:
    """Every number an app's prose states and how often, commas stripped.

    Counted rather than collected into a set: see `frozen`.
    """
    return dict(Counter(n.replace(",", "") for n in NUMBER.findall(prose(app))))


def test_the_figure_fixture_covers_every_app():
    """A fixture listing nine of ten apps would let the tenth drift untouched."""
    assert set(frozen()) == {app.name for app in APPS}


def test_the_fixture_holds_every_figure_it_claims_to():
    """A sweep over empty sets passes, and so does a comparison of two of them."""
    held = frozen()
    # Distinct figures, and the total number of statements of them. Both, because the
    # first is what the old set-shaped fixture pinned and the second is what it missed.
    assert sum(len(v) for v in held.values()) == 106, {k: len(v) for k, v in held.items()}
    assert sum(sum(v.values()) for v in held.values()) == 206, {
        k: sum(v.values()) for k, v in held.items()
    }
    assert all(held.values()), [k for k, v in held.items() if not v]


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_no_figure_in_an_apps_prose_changes_without_the_fixture_changing(app: Path):
    found, held = figures(app), frozen()[app.name]
    gained = sorted(f"{k} x{v}" for k, v in found.items() if held.get(k) != v)
    lost = sorted(f"{k} x{v}" for k, v in held.items() if found.get(k) != v)
    assert not (gained or lost), (
        f"{app.name}'s prose figures moved."
        + (f" Was: {', '.join(lost)}." if lost else "")
        + (f" Now: {', '.join(gained)}." if gained else "")
        + " If deliberate, run `python scripts/freeze_app_figures.py`."
    )


def test_how_much_of_the_prose_the_arithmetic_checks_actually_reach():
    """The coverage of the two checks below, asserted rather than assumed.

    Without this, the eight apps those regexes do not match are eight silent passes.
    With it, a drop in coverage fails here and the number is in the failure message.
    """
    reached = {app.name: len(OF_WITH_PCT.findall(prose(app))) for app in APPS}
    covered = sorted(name for name, n in reached.items() if n)
    assert covered == ["02_false_accepts"], (
        f"arithmetic coverage changed: {reached}. One app of ten is reached by the "
        "'N of M (P%)' shape; the rest state their figures in prose no pattern pairs "
        "up, and are held only by STATED_FIGURES."
    )
    assert sum(reached.values()) == 1


def test_the_two_apps_with_a_committed_run_are_the_two_that_can_be_verified():
    """So "checked against a run" and "pinned by count" are never confused.

    Eight apps' figures came from runs needing both model sizes on a GPU. Nothing
    offline can check them, and claiming otherwise is the defect this file is about.
    """
    verifiable = sorted(app.name for app in APPS if summary(app) is not None)
    assert verifiable == ["02_false_accepts", "03_vuln_baseline"]
    assert len(verifiable) < len(APPS)


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
    # Two numbers, because the panel was publishing one. The authors hand-verified 427
    # rows; `load_mbpp` can use 413 of them, the other fourteen carrying no test that
    # names a function to run the reference against. This assertion read
    # `f"{san['problems']} problems the authors hand-verified"` - the usable count
    # attributed to the authors - which is the conflation itself, asserted.
    from apps._engine.datasets import mbpp_population

    population = mbpp_population("sanitized")
    assert population.usable == san["problems"], (population.usable, san["problems"])
    assert f"{population.rows} problems the authors hand-verified" in text
    assert f"{population.usable} of them with tests" in text
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
    """The figures of a run that was replaced, which must not survive in the prose.

    `"427 problems"` used to be on this list and has been taken off it. 427 is the real
    row count of `sanitized-mbpp.json` - the superseded claim was using it as the
    population the rates are *over*, and banning the string stopped the file ever
    stating the true size of its own input. The ban is now on the denominator, which is
    the thing that was wrong: `of 427` in a sentence about mutants or survival.
    """
    text = prose(APPS[1]) + (ROOT / "README.md").read_text(encoding="utf-8")

    # Unambiguous anywhere: these say app 02's superseded run whatever surrounds them.
    for gone in ("5,116", "442", " 782", "25.3%"):
        assert gone not in text, f"{gone} is from the superseded run"

    # Ambiguous as bare strings, so banned as the CLAIM rather than as the number.
    # `16.0%` is app 06's real figure - "16.0% of description-written suites agree with
    # the reference" - and banning the four characters anywhere in the root README
    # meant the root could not quote app 06 to its own precision. A number is not a
    # claim; the number in its sentence is.
    for gone in ("17.6% of", "17.6% survival", "16.0% of 5", "16.0% of the mutants"):
        assert gone not in text, f"{gone!r} is from the superseded run"

    # And inside app 02's own prose, where they can only mean the one thing.
    only_02 = prose(APPS[1])
    for gone in ("17.6%", "16.0%"):
        assert gone not in only_02, f"{gone} is from the superseded run"
    for over in ("of 427 ", "of 427,", "of 427.", "over 427", "across 427"):
        assert over not in text, f"{over!r} makes 427 the scored population; it is 413"


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


# -- app 03's second column, which nothing used to compute ----------------


def test_app_03_computes_the_label_noise_column_its_docstring_describes():
    """The paragraph described a second results column and claimed a figure for it.

    An independent review grepped the whole app for the word and found one hit - the
    sentence making the claim. No dedup code, no second score in the result dict,
    nothing in the template, no field in the committed summary. And "it moves accuracy
    by a tenth of a point" is itself a model-derived figure, six lines under a sentence
    refusing to quote one.

    It is computed now, and the real number is smaller than the claim: one function
    body in 2,732 rows is duplicated with conflicting labels.
    """
    import importlib.util

    app = next(a for a in APPS if a.name == "03_vuln_baseline")
    spec = importlib.util.spec_from_file_location("vuln_baseline", app / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "conflicting_duplicates"), "the column is described, not computed"

    run = summary(app)
    noise = run["label_noise"]
    assert noise["rows"] == run["rows"]
    assert noise["distinct_bodies"] + noise["exact_duplicate_rows"] == noise["rows"]
    assert noise["bodies_with_conflicting_labels"] == 1
    assert noise["rows_dropped"] == 2
    assert noise["always_safe_all_rows"] == run["always_safe"]

    # The whole point: removing the noise moves the baseline by almost nothing.
    assert noise["shift_in_points"] < 0.01
    assert abs(
        noise["always_safe_conflicts_removed"] - noise["always_safe_all_rows"]
    ) * 100 == pytest.approx(noise["shift_in_points"])

    text = flat(regions(app)["docstring"])
    assert "one** function body in the 2,732-row test split" in text.replace("*", "*")
    assert "54.06% to 54.07%" in text
    assert "0.003 of a point" in text
    assert "a tenth of a point" not in text or "used to claim" in text


def test_app_03_still_declines_to_quote_a_model_accuracy():
    """And now there is a number in that paragraph which is not one.

    The old guard asserted the disclaimer string was present and never checked that
    no model figure followed it - a checker that could not fail for the thing it was
    named after. The figures in that paragraph are now baseline shares, which are
    computed from the labels alone.
    """
    app = next(a for a in APPS if a.name == "03_vuln_baseline")
    text = flat(regions(app)["docstring"])
    assert "The model's own accuracy is deliberately not quoted here" in text
    assert "Run it to get one" in text

    run = summary(app)
    model_free = {
        f"{run['always_safe'] * 100:.2f}",
        f"{run['label_noise']['always_safe_conflicts_removed'] * 100:.2f}",
        f"{run['always_safe'] * 100:.1f}",
        f"{run['first_800_safe_share'] * 100:.1f}",
        f"{run['seeded_800_safe_share'] * 100:.1f}",
    }
    quoted = {m for m in NUMBER.findall(text) if "." in m}
    unexplained = {q for q in quoted if q not in model_free and q not in {"2,732", "0.003"}}
    assert unexplained == set(), (
        f"figures in the paragraph with no source in the committed run: {sorted(unexplained)}"
    )


# -- the prompt asymmetry between apps ------------------------------------


def test_which_apps_hand_the_model_one_of_the_benchmarks_asserts():
    """It was invisible and it was load-bearing.

    App 04 reports the 14B at 76.0% on MBPP from its task description; app 10 reports
    48.0% for the same thing. App 04's prompt carries "It must satisfy this test:
    {test}" and app 10's `direct` arm does not - an assert pins the signature, the
    return type and one input/output pair. The root README prints both figures and
    attributes the whole 32.5-point gap to a leak in the generated description.

    Pinned as a table, so adding or removing the assert from any app is a deliberate
    edit here. App 08 exists to measure prompt sensitivity and nobody had applied it
    to the repository's own cross-app baselines.
    """
    carries_assert = {
        app.name: "It must satisfy this test" in (app / "app.py").read_text(encoding="utf-8")
        for app in APPS
    }
    assert carries_assert == {
        "01_localizer": False,
        "02_false_accepts": False,
        "03_vuln_baseline": False,
        "04_size_curve": True,
        "05_debug_ceiling": True,
        "06_kill_rate": False,
        "07_repair_rewrite": True,
        "08_prompt_shapes": True,
        "09_temperature": True,
        "10_roundtrip": True,  # in `direct_with_test` only, which is the point
    }, carries_assert


def test_app_10_has_the_arm_that_resolves_the_confound():
    """Three arms, not two, and the description-only one is unchanged.

    Replacing `direct` would make the published 48.0% unreproducible and dropping the
    assert from app 04 would do the same to its 76.0%, so the third condition is added
    rather than either being edited.
    """
    app = next(a for a in APPS if a.name == "10_roundtrip")
    source = (app / "app.py").read_text(encoding="utf-8")

    assert 'IMPLEMENT_WITH_TEST = """' in source
    assert '["direct", "direct_with_test", "roundtrip"]' in source
    assert "total = n * 4" in source, "the progress bar has to count four passes"

    text = flat(regions(app)["docstring"])
    assert "32.5 is" in text or "32.5 points" in text
    assert "upper bound" in text, "the gap has to be stated as a bound until it is measured"


def test_the_root_readme_states_the_confound_too():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    bullet = readme[readme.index("Describing the reference code") :]
    bullet = bullet[: bullet.index("\n\n")]
    assert "upper bound" in bullet
    assert "76.0%" in bullet and "48.0%" in bullet
    assert "direct_with_test" in bullet


# -- a rate has to be reachable over the population it is quoted over ---------

#: "18.0% of 4,055 mutants", "48.0% on 200 MBPP tasks": a percentage and, beside it,
#: the population it is over. Deliberately adjacent-only. Reading the population from
#: the enclosing sentence instead reaches three more apps and is wrong twice:
#: `01_localizer` writes "55.8% on that hard half" in a sentence that opens with 51
#: instances, and `06_kill_rate` quotes 93.4% over the valid suites in a sentence
#: about 150 tasks. A check that flags a correct figure teaches a reader to ignore it.
RATE_OVER_POPULATION = re.compile(
    r"(\d+\.\d|\d+)%\s*(?:of|on|over)\s+(?:the\s+)?([\d,]+)\s+"
    r"(?:MBPP\s+)?(tasks|mutants|problems|rows|instances|suites)"
)

#: The prose quotes one decimal, so a stated rate may sit this far from the truth.
QUOTED_PRECISION = 0.0005


def _reachable(pct: float, population: int) -> tuple[bool, float, int]:
    """Is `pct`% of `population` a rate `population` items can produce?

    Returns (reachable, distance to the nearest achievable rate, that numerator).
    A population of N can only produce k/N, so a quoted rate further than half a
    quoted decimal from every k/N is a rate no run of that size produced.
    """
    target = pct / 100
    numerator = round(target * population)
    return (
        abs(numerator / population - target) <= QUOTED_PRECISION + 1e-12,
        abs(numerator / population - target),
        numerator,
    )


def _rate_claims(app: Path) -> list[tuple[float, int, str]]:
    text = " ".join(prose(app).split())
    return [
        (float(pct), int(n.replace(",", "")), unit)
        for pct, n, unit in RATE_OVER_POPULATION.findall(text)
    ]


@pytest.mark.parametrize("app", APPS, ids=[p.name for p in APPS])
def test_every_rate_quoted_over_a_population_is_one_that_population_can_produce(app: Path):
    """Arithmetic, so it holds for the eight apps nothing offline can re-measure."""
    for pct, population, unit in _rate_claims(app):
        ok, distance, numerator = _reachable(pct, population)
        assert ok, (
            f"{app.name}: {pct}% of {population} {unit} is not a rate {population} "
            f"items can produce - the nearest is {numerator}/{population} = "
            f"{numerator / population * 100:.3f}%, {distance * 100:.3f} points away"
        )


def test_how_many_of_those_rates_the_arithmetic_can_actually_falsify():
    """A population finer than the quoted precision makes the check unfalsifiable.

    At 4,055 mutants every one-decimal percentage is reachable, and so it is at
    1,553: two of the four pairs cannot fail and two can. Printed rather than averaged into a
    coverage number, because "six rates checked" would read as six rates tested.
    """
    discriminating, total = [], 0
    for app in APPS:
        for pct, population, _unit in _rate_claims(app):
            total += 1
            # Can any one-decimal value over this population be rejected? Only if a
            # step between achievable rates is wider than the quoted precision.
            if 1 / population > 2 * QUOTED_PRECISION:
                discriminating.append(f"{app.name}:{pct}%/{population}")
    assert total == 4, total
    assert sorted(discriminating) == [
        "01_localizer:74.5%/51",
        "10_roundtrip:48.0%/200",
    ], sorted(discriminating)


def test_an_impossible_rate_is_rejected():
    """The check above passes on the repository as it stands, so it is also run
    against a figure that cannot be true: 60.1% of 250 tasks is 150.25 items."""
    assert _reachable(60.0, 250)[0]
    assert not _reachable(60.1, 250)[0]
    # And the unfalsifiable end, stated as a fact about the method rather than a
    # weakness to be worked around: at this population every value is reachable.
    assert _reachable(18.0, 4055)[0]
    assert _reachable(18.1, 4055)[0]


# -- every headline bullet, against the app that produced it --------------------------

#: A figure in the root README's "What they found" list -> the app whose prose is its
#: source. Each is a sentence a reader takes as this repository's finding, and four of
#: the six were in the root README and nowhere else that any test looked at: a reviewer
#: rewrote them to different numbers and the whole suite stayed green.
#:
#: The apps' own figures came from runs needing a GPU and both model sizes, so nothing
#: here can re-derive them. What this catches is the two copies drifting apart, which is
#: exactly the defect `02` and `10` are already checked for.
HEADLINE_BULLETS = {
    "54.1%": "03_vuln_baseline",
    "75.8%": "04_size_curve",
    "93.3%": "07_repair_rewrite",
    "93.4%": "06_kill_rate",
    "85.0%": "06_kill_rate",
    "16.0%": "06_kill_rate",
    # Rounds 3-5 added nothing "for 60% of the compute", in both files.
    "60% of the compute": "05_debug_ceiling",
}


def _root_findings() -> str:
    """The "What they found" bullets, which are the claims a reader acts on."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## What they found")
    rest = text[start + len("## What they found") :]
    end = rest.find("\n## ")
    section = rest[:end] if end != -1 else rest
    # Whitespace-collapsed: these are wrapped bullets, and a claim that spans a line
    # break is the same claim.
    return " ".join(section.split())


def test_the_findings_section_is_where_this_thinks_it_is():
    """A sweep over an empty string passes."""
    found = _root_findings()
    assert len(found) > 1_000, len(found)
    assert found.count("- **") >= 6, found.count("- **")


@pytest.mark.parametrize("figure", sorted(HEADLINE_BULLETS))
def test_every_headline_figure_is_still_in_the_root_readme(figure: str):
    """The mapping is only a cross-check while both sides hold the figure."""
    assert figure in _root_findings(), (
        f"{figure} has left the root README's findings. If the finding changed, this "
        "table changes with it; if it was deleted, so is its entry."
    )


@pytest.mark.parametrize("figure", sorted(HEADLINE_BULLETS))
def test_every_headline_figure_matches_the_app_that_produced_it(figure: str):
    """Two copies of a number, compared.

    This is weaker than re-deriving it and it is what is available: the runs needed a
    GPU. It is not nothing - the failure it catches is one copy being edited and the
    other not, which is how `17.6% of 5,116 mutants` survived in one file after the
    measurement said 18.0% of 4,055 in the other.
    """
    app = ROOT / "apps" / HEADLINE_BULLETS[figure]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [app / "app.py", *sorted((app / "templates").glob("*.html"))]
        if path.is_file()
    )
    assert figure in source, (
        f"the root README states {figure} and {app.name} does not. One of the two copies "
        "was edited and the other was not."
    )


def test_the_devign_baseline_is_derived_from_the_committed_split():
    """54.1% is the one headline figure that needs no model, so it is computed.

    The always-SAFE baseline is a property of the file: the share of
    `data/benchmarks/devign_test.parquet` rows labelled safe IS the number.

    This used to say that and not do it. It checked the parquet's `PAR1` magic, unpacked
    the footer length, asserted `len(metadata) == footer_length` - which is true by slice
    construction - and then divided `summary["safe"]` by `summary["rows"]`, both out of
    `apps/results/03_vuln_baseline.json`. No label was read, so inverting every `target`
    in the parquet left all five of this app's tests passing, and the only figure the
    repository offers as model-free was pinned to the file that states it.

    The labels are read now, and the committed summary is checked AGAINST them rather
    than used as them.
    """
    import json

    pandas = pytest.importorskip(
        "pandas",
        reason="the labels cannot be read without a parquet reader, and asserting the "
        "summary against itself is what this test was written to stop",
    )

    path = ROOT / "data" / "benchmarks" / "devign_test.parquet"
    assert path.is_file(), path

    frame = pandas.read_parquet(path, columns=["target"])
    rows = len(frame)
    # `target` is 0/1 in the published dataset and arrives as a boolean here; both are
    # falsy for safe, which is the only property this depends on.
    safe = int((~frame["target"].astype(bool)).sum())
    assert rows > 0, path
    share = safe / rows

    summary = json.loads(
        (ROOT / "apps" / "results" / "03_vuln_baseline.json").read_text(encoding="utf-8")
    )
    # The committed summary is now the thing being CHECKED, against the file.
    assert summary["rows"] == rows, (summary["rows"], rows)
    assert summary["safe"] == safe, (summary["safe"], safe)
    assert summary["vulnerable"] == rows - safe, summary
    assert abs(summary["always_safe"] - share) < 1e-9, (summary["always_safe"], share)

    assert f"{share * 100:.1f}%" == "54.1%", share
    readme = _root_findings()
    assert f"{share * 100:.1f}%" in readme, share

