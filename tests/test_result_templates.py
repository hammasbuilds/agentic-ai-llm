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
    out: set[str] = set()
    for template in (
        sorted((app / "templates").glob("*.html")) if (app / "templates").is_dir() else []
    ):
        out |= set(FIELD.findall(template.read_text(encoding="utf-8")))
    return out


CHECKABLE = [app for app in APPS if _runner_keys(app) is not None and _template_fields(app)]


def test_there_are_apps_to_check():
    """A sweep over an empty list passes, and ten apps have a runner and a template."""
    assert len(APPS) == 10, [a.name for a in APPS]
    assert len(CHECKABLE) >= 8, [a.name for a in CHECKABLE]


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
