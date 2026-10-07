"""Every field a result template reads is one its app's runner returns.

An independent review raised the risk: `job_result` now catches `Exception` around
`TemplateResponse` and returns a 200 fragment, which is right for a result cached by an
older deploy and removes the only signal a template broken for the *correct* shape ever
had. It would ship as a muted paragraph with nothing failing.

The risk was already real. `apps/03_vuln_baseline/templates/result.html` read
`result.beats_baseline` in four places, and the runner had stopped returning it - the
code comment beside the change says why: "One field called `beats_baseline` hid which of
the two it meant", so it became `vs_always_safe` and `vs_majority` and the template was
not updated. A real run of that app rendered the fallback.

Checked statically, because the alternative is a model. `full` in app 03's result is
built from model answers, so there is no committed artefact of the shape the template
wants - which is exactly the condition under which a template rots unnoticed. Reading
the runner's `return` and the template's `result.X` references needs neither a model nor
a browser and catches the whole class.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APPS = sorted(p for p in (ROOT / "apps").glob("[0-9]*") if (p / "app.py").is_file())

#: `result.a.b` -> the top-level key `a`. Jinja attribute access on a dict.
FIELD = re.compile(r"\bresult\.([A-Za-z_]\w*)")

#: `result.get('witnesses')` -> `witnesses`. The explicit form a template uses for a
#: field that may be absent from a particular result, which under `StrictUndefined` is
#: the only correct way to read one. Matched separately because `FIELD` reads the same
#: text as a field named `result.get`, and then reported that the runner had stopped
#: returning `get`.
OPTIONAL_FIELD = re.compile(r"""\bresult\.get\(\s*['"](\w+)['"]""")

#: Keys a template may read that no runner returns, with the reason. `job` and the
#: platform's own context are separate names in the template, so this is only for a
#: result key supplied somewhere other than the runner's return.
ALLOWED: dict[str, str] = {}


def _runner_keys(app: Path) -> set[str] | None:
    """The top-level keys `runner` returns, or None if they cannot be read statically.

    Every dict literal returned from `runner` is unioned: an app with an early return
    for a degenerate case has more than one, and a template has to cope with each.
    """
    tree = ast.parse((app / "app.py").read_text(encoding="utf-8"))
    runners = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "runner"
    ]
    if len(runners) != 1:
        return None
    keys: set[str] = set()
    literal_returns = 0
    for node in ast.walk(runners[0]):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            literal_returns += 1
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
                else:
                    return None  # a computed or splatted key: not readable here
    return keys if literal_returns else None


def _template_fields(app: Path) -> set[str]:
    """Every result key a template reads, however it reads it.

    `result.get("witnesses")` counts as reading `witnesses` and not as reading a field
    called `get`. It is still a field the runner has to return: the optional form says
    the key may be missing from a PARTICULAR result - one loaded from a committed
    summary, which holds counts and no artifacts - not that no runner produces it.
    """
    out: set[str] = set()
    for template in (
        sorted((app / "templates").glob("*.html")) if (app / "templates").is_dir() else []
    ):
        text = template.read_text(encoding="utf-8")
        out |= set(FIELD.findall(text)) | set(OPTIONAL_FIELD.findall(text))
    return out - {"get"}


CHECKABLE = [app for app in APPS if _runner_keys(app) is not None and _template_fields(app)]

#: An app whose result template cannot be checked statically, and why. Empty, because
#: all ten can be: each has one `runner` returning dict literals with string keys, and
#: each template reads at least one `result.X`.
#:
#: By name rather than by a floor. This said `len(CHECKABLE) >= 8` over ten apps, so
#: two could leave the parametrisation without failing anything - and leaving it is
#: silent by construction: `_runner_keys` returns None for a runner that builds its
#: result with `**` or a computed key, which is a refactor, not a deletion. The test
#: that was written because one template had rotted would simply stop covering it.
UNCHECKABLE: dict[str, str] = {}


def test_every_app_is_checked_or_listed_as_an_exception():
    """A sweep over an empty list passes, and ten apps have a runner and a template."""
    assert len(APPS) == 10, [a.name for a in APPS]
    names = {a.name for a in APPS}
    checked = {a.name for a in CHECKABLE}
    assert UNCHECKABLE.keys() <= names, sorted(UNCHECKABLE.keys() - names)
    unchecked = sorted(names - checked)
    assert unchecked == sorted(UNCHECKABLE), (
        f"{unchecked} have a result template that nothing here reads. Either their "
        "runner stopped returning a readable dict - which is the condition a rotted "
        "template hides in - or they belong in UNCHECKABLE with the reason."
    )


def test_an_exception_says_what_cannot_be_read():
    """An allowlist is a list of claims; one without a reason is a silenced failure."""
    for name, reason in sorted(UNCHECKABLE.items()):
        assert len(reason) > 20, f"{name}: {reason!r} does not say why"


@pytest.mark.parametrize("app", CHECKABLE, ids=lambda p: p.name)
def test_every_field_the_template_reads_is_one_the_runner_returns(app: Path):
    returned = _runner_keys(app)
    read = _template_fields(app)
    missing = sorted(field for field in read - returned if field not in ALLOWED)
    assert not missing, (
        f"{app.name}: the result template reads {missing}, and `runner` returns "
        f"{sorted(returned)}. A field the runner stopped producing renders as the "
        "fallback fragment, which is a 200."
    )


@pytest.mark.parametrize("app", CHECKABLE, ids=lambda p: p.name)
def test_the_template_reads_something(app: Path):
    """A template that reads no field cannot be checked by the test above, and would
    satisfy it trivially."""
    assert _template_fields(app), app.name


def test_the_field_that_was_missing_is_named():
    """A count alone is satisfied by deleting the template. This pins the one case."""
    template = (ROOT / "apps" / "03_vuln_baseline" / "templates" / "result.html").read_text(
        encoding="utf-8"
    )
    assert "beats_baseline" not in template, "the split field name is back"
    assert "vs_always_safe" in template, "the replacement is gone"
    returned = _runner_keys(ROOT / "apps" / "03_vuln_baseline")
    assert {"vs_always_safe", "vs_majority"} <= returned, sorted(returned)


# -- the environment that makes a missing field visible -----------------------


def test_the_template_environment_raises_on_a_field_that_is_not_there():
    """Jinja's default prints an undefined as "", which is how app 03 shipped.

    `{{ result.beats_baseline }}` over a result that no longer carried the key
    rendered a page with a gap in it and returned 200. The static check above catches
    the case where the runner's literal returns can be read; `StrictUndefined` catches
    the rest at render time, and `job_result` turns the error into the fragment that
    names the keys the result does have.

    Asserted on a built app, not by reading `base.py` for the word: what matters is
    the environment the renderer uses, and `create_app` now puts it on `app.state`
    for exactly that reason.
    """
    import sys

    from jinja2 import StrictUndefined

    sys.path.insert(0, str(ROOT))
    from apps._platform.base import create_app

    app = create_app(
        slug="localizer",
        icon="target",
        runner=lambda **_kw: {},
        fields=[],
        result_template="result.html",
        about="<p>built here to read the environment off the app</p>",
        templates_dir=ROOT / "apps" / "01_localizer" / "templates",
    )
    assert app.state.templates.env.undefined is StrictUndefined


def test_an_optional_field_is_read_as_optional():
    """`witnesses` is the only one, and it is optional for a stated reason.

    `apps/results/` commits the integers a run produced and not its artifacts, so a
    result loaded from a committed summary has no witness rows. Under the default
    undefined `{% if result.witnesses %}` was silently false; under the strict one it
    raised, and the fix is the template saying the field may be absent rather than the
    environment going back to hiding it.
    """
    import re

    template = (ROOT / "apps" / "02_false_accepts" / "templates" / "result.html").read_text(
        encoding="utf-8"
    )
    assert "result.get('witnesses')" in template
    assert not re.search(r"\{%\s*if\s+result\.witnesses\s*%\}", template)

    # And no other template guards a field with a bare `if result.x` while the runner
    # for that app does not return it - which is the same defect waiting to happen.
    guarded = {}
    for app in CHECKABLE:
        for template_path in (app / "templates").glob("*.html"):
            text = template_path.read_text(encoding="utf-8")
            for field in re.findall(r"\{%\s*if\s+result\.(\w+)\s*%\}", text):
                guarded.setdefault(app.name, set()).add(field)
    for name, fields in sorted(guarded.items()):
        returned = _runner_keys(next(a for a in CHECKABLE if a.name == name))
        assert fields <= returned, f"{name}: {sorted(fields - returned)}"
