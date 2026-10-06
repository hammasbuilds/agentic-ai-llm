"""No app publishes a number from a run the model did not answer.

`tests/test_platform_degraded.py` names this harm one layer lower:

    "A substitute answer from a missing model would be scored as the model's output,
     and every number these apps publish would be measuring the fallback."

...and then asserted that a job with the model at a closed port came back `done` with a
truthy `result`. It did: `{"per_round": [0,0,0,0,0], "final_pass": 0.0}`. An independent
review drove it further — with the model dying part-way through, app 04 published the 3B
beating the 14B by 25 points and solving 100% of what either could solve, from a run in
which seven eighths of the calls never reached a model. Status `done`.

`grep -rn "runner(" tests/` returned nothing before this file. Four tests covered all
ten apps and checked that each loads, has a unique slug, and has a result template.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._platform import bus, cache, model  # noqa: E402

APPS = sorted(p.name for p in (ROOT / "apps").iterdir() if (p / "app.py").is_file())
_LOADED: dict[str, object] = {}


def load(name: str):
    if name not in _LOADED:
        spec = importlib.util.spec_from_file_location(
            f"runner_{name}", ROOT / "apps" / name / "app.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[name] = module
    return _LOADED[name]


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch):
    """Every dependency at a closed port, and every generation lost.

    `generate` is stubbed rather than left to fail, so the test is about what a runner
    does with a lost generation and not about how long a connection takes.
    """
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(bus, "_producer", None)
    monkeypatch.setattr(bus, "_available", False)
    monkeypatch.setattr(model, "OLLAMA", "http://127.0.0.1:1")

    async def nothing(*_args, **_kwargs):
        return None

    async def nothing_many(prompts, **_kwargs):
        return [None] * len(prompts)

    monkeypatch.setattr(model, "generate", nothing)
    monkeypatch.setattr(model, "generate_many", nothing_many)


def uses_the_model(name: str) -> bool:
    """Whether this app generates at all.

    02_false_accepts does not: it mutates reference solutions and runs their tests, so
    there is no generation to lose. Asked of the source rather than hardcoded, so an
    app that starts generating is covered the day it does.
    """
    source = (ROOT / "apps" / name / "app.py").read_text(encoding="utf-8")
    return "model.generate" in source


@pytest.mark.parametrize("name", APPS)
def test_no_app_publishes_a_number_from_a_run_the_model_did_not_answer(name, no_model):
    """Refused, loudly. Not a finished measurement of nothing."""
    module = load(name)
    runner = getattr(module, "runner", None)
    assert runner is not None, f"{name} has no runner"

    async def emit(*_args, **_kwargs):
        return None

    params = {field.name: field.default for field in module.app.state.fields}
    params["limit"] = min(int(params.get("limit") or 2), 2)

    if not uses_the_model(name):
        # It measures without generating, so a lost generation cannot reach its numbers.
        result = asyncio.run(runner(params, emit))
        assert isinstance(result, dict) and result, name
        return

    with pytest.raises(Exception) as caught:  # noqa: B017 - the kind is asserted below
        asyncio.run(runner(params, emit))
    message = str(caught.value)
    assert isinstance(caught.value, (model.ModelUnreachable, ValueError)), (name, message)
    assert "never reached the model" in message or "model" in message.lower(), (name, message)


def test_the_apps_that_generate_are_the_ones_this_file_thinks_they_are():
    """A parametrised test that silently stopped covering nine apps would still pass."""
    generating = sorted(name for name in APPS if uses_the_model(name))
    assert len(generating) == 9, generating
    assert "02_false_accepts" not in generating


def test_a_lost_generation_is_not_an_empty_answer():
    """The helper itself. An empty string is a wrong answer; a lost call is not one."""
    assert model.require_all(["a", "b"]) == ["a", "b"]
    assert model.require_all([""]) == [""]  # an empty ANSWER is still an answer

    with pytest.raises(model.ModelUnreachable) as caught:
        model.require_all(["a", None, "c"], what="attempt")
    assert "1 of 3 attempts never reached the model" in str(caught.value)


def test_availability_is_about_this_model_not_its_family(monkeypatch):
    """ "qwen2.5-coder:14b".split(":")[0] in r.text was true for any tag of that family.

    So an app comparing a 3B against a 14B showed a green badge and an enabled Run
    button for a size the server does not hold, and then published the comparison with
    one arm entirely fabricated.
    """
    held = ("qwen2.5-coder:14b", "nomic-embed-text:latest")

    async def tags():
        return held

    monkeypatch.setattr(model, "tags", tags)
    assert asyncio.run(model.available("qwen2.5-coder:14b")) is True
    assert asyncio.run(model.available("qwen2.5-coder")) is True
    assert asyncio.run(model.available("qwen2.5-coder:3b")) is False
    assert asyncio.run(model.available("qwen2.5-coder:does-not-exist")) is False
    assert asyncio.run(model.available("nomic-embed-text")) is True


def test_an_unreachable_server_is_asked_once_not_once_per_page(monkeypatch):
    """`cache` and `bus` both remember a failure for a while; `model` did not — and it
    is the one `health()` calls, which every page handler calls. That was the floor on
    every page render of every app."""
    calls = 0

    class Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise __import__("httpx").ConnectError("nope")

    monkeypatch.setattr(model, "_down_until", 0.0)
    monkeypatch.setattr(model, "httpx", __import__("httpx"))
    monkeypatch.setattr(model.httpx, "AsyncClient", lambda **_kw: Boom())

    for _ in range(5):
        assert asyncio.run(model.available()) is False
    assert calls == 1, f"asked {calls} times for one answer"


# ---- the baseline a model is compared against ----------------------------------------


def test_the_devign_baselines_are_what_the_prose_says():
    """The headline ran the comparison backwards, twice over.

    `majority` is the larger class, and on a nearly balanced sample that is VULNERABLE —
    so a sentence about "always answers safe" was compared against the opposite constant.
    And the sample was the first N rows of the file, which are 49.6% safe where the split
    is 54.1%, so the baseline moved four and a half points depending on where the file
    started. 50.0% was reported as *below* always-SAFE when on those rows it was above it.
    """
    import random

    module = load("03_vuln_baseline")
    frame = module._load_devign("test")
    total = len(frame)
    vulnerable = sum(bool(frame["target"].iloc[i]) for i in range(total))
    always_safe = (total - vulnerable) / total
    assert round(always_safe, 3) == 0.541, always_safe

    # The front of the file is not the split.
    front = [bool(frame["target"].iloc[i]) for i in range(800)]
    assert round(sum(1 for v in front if not v) / len(front), 3) == 0.496

    # The seeded sample is, to within a couple of points, at every limit the form allows.
    for take in (120, 400, 800):
        order = random.Random(0).sample(range(total), take)
        labels = [bool(frame["target"].iloc[i]) for i in order]
        safe_share = sum(1 for v in labels if not v) / len(labels)
        assert abs(safe_share - always_safe) < 0.03, (take, safe_share)


def test_both_constants_are_reported_not_only_the_larger():
    """One field called `beats_baseline` hid which of the two it meant."""
    module = load("03_vuln_baseline")
    # 7 safe, 3 vulnerable; a classifier that always says SAFE scores 0.7.
    pairs = [(False, False)] * 7 + [(False, True)] * 3
    scored = module._score(pairs)
    assert scored["always_safe"] == 0.7
    assert scored["always_vulnerable"] == 0.3
    assert scored["majority"] == 0.7
    assert scored["accuracy"] == 0.7


# -- a rate over the rows the model agreed to classify --------------------


def _vuln_baseline():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vuln_baseline_floor", ROOT / "apps" / "03_vuln_baseline" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PartiallyParsable:
    """Answers `parsable` of the prompts and waffles at the rest."""

    def __init__(self, parsable: int):
        self.parsable = parsable

    async def generate_many(self, prompts, **kwargs):
        return ["SAFE"] * self.parsable + ["I am not sure"] * (len(prompts) - self.parsable)

    def require_all(self, raws, what: str = ""):
        return list(raws)


async def _nothing(*args, **kwargs):
    return None


def test_app_03_refuses_a_rate_over_the_rows_the_model_happened_to_answer(monkeypatch):
    """It used to report one, and only a 100%-unparsed run raised.

    `require_all` refuses to publish a rate when a generation never reached the
    model. This is the same principle one step along: a generation that arrived and
    could not be read is not a row the model got wrong, and the rows a model declines
    to classify are not a random sample - unparsability tracks difficulty. So an
    accuracy over the survivors selects for the easy ones, which is a worse selection
    than the front-of-file sample this app exists to criticise.
    """
    module = _vuln_baseline()
    monkeypatch.setattr(module, "model", _PartiallyParsable(3))

    with pytest.raises(ValueError, match="no rate is published below"):
        asyncio.run(module.runner({"limit": 10}, _nothing))


def test_app_03_reports_a_rate_when_nearly_everything_parsed(monkeypatch):
    module = _vuln_baseline()
    monkeypatch.setattr(module, "model", _PartiallyParsable(10))

    out = asyncio.run(module.runner({"limit": 10}, _nothing))
    assert out["rows"] == 10
    assert out["parsed"] == 10
    assert out["parsed_share"] == 1.0
    assert out["unparsed"] == 0


def test_app_03_compares_against_the_splits_baseline_not_the_subsamples(monkeypatch):
    """The baseline is a property of the data, so it must not move with the model.

    `_score` recomputes `always_safe` over the pairs it was given, so a model scored
    on the rows it answered was compared against a baseline recomputed for those same
    rows. `always_safe_over_all_rows` is the constant over every row read.
    """
    module = _vuln_baseline()
    monkeypatch.setattr(module, "model", _PartiallyParsable(9))

    out = asyncio.run(module.runner({"limit": 10}, _nothing))
    assert out["parsed"] == 9
    assert "always_safe_over_all_rows" in out
    assert out["always_safe_over_all_rows"] == pytest.approx(
        out["full"]["always_safe"] * out["parsed"] / out["rows"], abs=0.2
    ), "the two baselines should be close here, and they are different numbers"
    assert out["vs_always_safe_over_all_rows"] == pytest.approx(
        out["full"]["accuracy"] - out["always_safe_over_all_rows"]
    )


def test_the_floor_is_a_declared_constant_not_a_magic_number():
    module = _vuln_baseline()
    assert 0.5 < module.MIN_PARSED_SHARE <= 1.0
