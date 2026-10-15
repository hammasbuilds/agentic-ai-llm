"""The run log, and the console's arithmetic over it.

Four properties carry the weight:

  * **Off unless asked.** Every `runtime()` here falls back to an in-memory bus and store
    rather than requiring a broker; a build that started writing to disk on install would
    be the one component that did not keep that promise.
  * **The parameters and the error text stay out of the file.** A measurement's
    parameters can hold a pasted issue report and an exception message can hold a path.
    The error's TYPE is recorded, because what a console needs is which failure keeps
    happening.
  * **Both transports record.** `_run_inline` and the worker's `handle` are different
    code paths to the same outcome, and instrumenting one would have made every job that
    went over the bus invisible - which, with nothing binding Kafka today, looks exactly
    like the truth until somebody starts the worker.
  * **Recording cannot break a job.** It is called from the error branch, where something
    has already gone wrong; a telemetry exception there would replace a measurement's real
    error with this module's.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from apps._platform import base, cache, telemetry

ROOT = Path(__file__).resolve().parents[1]

#: Distinctive, so "the parameters do not reach the log" is checkable rather than hopeful.
SECRET_PARAM = "zarcon-pelagic-parameter"


def _collect():
    """`observability/collect.py` - the console's arithmetic, not part of the package."""
    spec = importlib.util.spec_from_file_location(
        "aal_observability_collect", ROOT / "observability" / "collect.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _good(params, emit):
    await emit(1, 1, "")
    return {"total": 7}


async def _bad(params, emit):
    raise RuntimeError(f"no model reachable for {params.get('note')}")


def _run(app: str, runner) -> None:
    async def once():
        job_id = f"test-{app}-{id(runner)}"
        await cache.create_job(job_id, app, {"note": SECRET_PARAM})
        await base._run_inline(app, job_id, {"note": SECRET_PARAM}, runner)

    asyncio.run(once())


def test_nothing_is_written_when_the_variable_is_unset(tmp_path, monkeypatch):
    """The default, asserted over a directory rather than over the function."""
    monkeypatch.delenv(telemetry.ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert telemetry.destination() is None
    _run("01_localizer", _good)
    assert list(tmp_path.rglob("*")) == []


def test_a_finished_job_is_recorded(tmp_path, monkeypatch):
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(telemetry.ENV, str(log))
    _run("01_localizer", _good)

    written = log.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in written if line.strip()]
    assert len(rows) == 1
    assert rows[0]["app"] == "01_localizer"
    assert rows[0]["outcome"] == "done"
    assert rows[0]["transport"] == "inline"
    assert rows[0]["items"] == 7
    assert rows[0]["seconds"] >= 0


def test_a_failed_job_is_recorded_as_one(tmp_path, monkeypatch):
    """A console whose failure panel has never been rendered is one nobody has seen work."""
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(telemetry.ENV, str(log))
    _run("02_false_accepts", _bad)

    written = log.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in written if line.strip()]
    assert [r["outcome"] for r in rows] == ["error"]
    assert rows[0]["error"] == "RuntimeError"


def test_the_parameters_and_the_error_text_stay_out_of_the_log(tmp_path, monkeypatch):
    """The one that would be embarrassing to get wrong."""
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(telemetry.ENV, str(log))
    _run("01_localizer", _good)
    _run("02_false_accepts", _bad)

    written = log.read_text(encoding="utf-8")
    assert SECRET_PARAM not in written, "a job parameter reached the log"
    assert "no model reachable" not in written, "an error message reached the log"
    # ...while the error's type did, which is what the panel is for.
    assert "RuntimeError" in written


def test_an_unwritable_destination_does_not_break_a_job(tmp_path, monkeypatch):
    """Recording is called from the error branch, where something has already failed."""
    blocked = tmp_path / "a-directory"
    blocked.mkdir()
    monkeypatch.setenv(telemetry.ENV, str(blocked))
    _run("01_localizer", _good)  # must not raise


def test_the_worker_records_the_other_transport():
    """Both paths, asserted by reading them rather than by running a broker.

    `worker.py` is the Kafka path and `base._run_inline` the in-process one. They are
    separate code with the same outcome, and only one of them being instrumented is the
    failure this guards: with nothing binding Kafka today, a missing `transport: kafka`
    would look exactly like the truth.
    """
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    assert "telemetry.job(" in worker, "the worker records nothing"
    assert 'transport="kafka"' in worker

    platform = (ROOT / "apps" / "_platform" / "base.py").read_text(encoding="utf-8")
    assert "telemetry.job(" in platform
    assert 'transport="inline"' in platform


def test_the_log_rotates_rather_than_growing_without_bound(tmp_path, monkeypatch):
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(telemetry.ENV, str(log))
    monkeypatch.setattr(telemetry, "MAX_BYTES", 400)
    for index in range(80):
        telemetry.job("01_localizer", "done", 1.0, transport="inline", items=index)
    assert log.with_suffix(".jsonl.1").exists(), "nothing was rotated"
    assert log.stat().st_size < 4000


def test_a_half_written_line_does_not_empty_the_console(tmp_path):
    collect = _collect()
    log = tmp_path / "runs.jsonl"
    good = json.dumps({"at": 1.0, "app": "01_localizer", "outcome": "done", "seconds": 1.0})
    log.write_text(good + "\n" + good + "\n" + '{"at": 3.0, "app": "01_loc', encoding="utf-8")
    assert len(collect.read(log)) == 2


def test_the_transport_split_is_counted(tmp_path):
    """`inline: 100%` is a fact about this repository, not a misconfiguration."""
    collect = _collect()
    log = tmp_path / "runs.jsonl"
    log.write_text(
        "".join(
            json.dumps(
                {
                    "at": float(i),
                    "app": "01_localizer",
                    "outcome": "done",
                    "seconds": 1.0,
                    "transport": t,
                }
            )
            + "\n"
            for i, t in enumerate(["inline", "inline", "kafka"])
        ),
        encoding="utf-8",
    )
    summary = collect.summarise(collect.read(log))
    assert summary["transports"] == {"inline": 2, "kafka": 1}


def test_an_app_that_has_never_run_has_no_failure_rate(tmp_path):
    """Zero and "no data" read the same on a dashboard and are not the same fact."""
    collect = _collect()
    empty = collect.summarise(collect.read(tmp_path / "absent.jsonl"))
    assert empty["runs"] == 0
    assert empty["failure_rate"] is None
    assert empty["first"] is None


def test_a_thin_sample_is_declared_rather_than_dressed_up(tmp_path):
    collect = _collect()
    log = tmp_path / "runs.jsonl"
    log.write_text(
        "".join(
            json.dumps(
                {"at": float(i), "app": "01_localizer", "outcome": "done", "seconds": float(i)}
            )
            + "\n"
            for i in range(3)
        ),
        encoding="utf-8",
    )
    summary = collect.summarise(collect.read(log))
    assert summary["thin"] is True
    assert summary["thin_at"] == collect.THIN
    assert summary["apps"][0]["thin"] is True
