"""powerguard against this machine.

Not a fixture: real processes, the real GPU, the real power state. The
assertions are written as properties rather than frozen counts, because what is
running changes — except where a count is the finding.
"""

import random

import pytest

from powerguard.domain import (
    DOWNLOAD,
    HIBERNATE,
    OTHER,
    TRAINING,
    Job,
    Machine,
    collateral,
    plan,
    unowned_at_risk,
)
from powerguard.machine import Process, gpu, jobs, power, processes

#: This machine's process table, read once. `processes()` shells out to
#: `powershell Get-CimInstance` and returns `[]` on any `OSError` or a 40-second
#: timeout, so this is empty on a container, on a host without powershell on PATH, and
#: on a machine loaded enough to miss the timeout.
HERE = processes()


@pytest.fixture(scope="module")
def live() -> list[Process]:
    """The real process table, or a skip.

    Requested by the nine tests that read the machine. It used to be a
    `pytestmark = pytest.mark.skipif(...)` on the module, which skipped all twenty -
    eleven of which touch no machine, and four of which monkeypatch every reading they
    use. On a host that cannot read processes the file reported `20 passed, 28 skipped`
    while `README.md` and `tests/fixtures/suite_counts.json` published 48 and 0, and
    the sweep printed `ok`.

    A fixture rather than a marker because the dependency belongs to the tests that
    have it. The README's "measured against a real process table, not a fixture" is
    about these nine, and they still refuse to pretend.
    """
    if not HERE:
        pytest.skip(
            "cannot read this host's process table: `powershell Get-CimInstance` "
            "failed or timed out. The nine tests that read the machine are the "
            "product's claim and are not simulated."
        )
    return HERE


def test_the_machine_is_readable(live):
    assert len(live) > 50
    # pid 0 is real on Windows: the System Idle Process.
    assert all(p.pid >= 0 for p in live)
    assert any(p.pid > 0 for p in live)


def test_the_power_state_is_read_not_assumed(live):
    m = power()
    assert isinstance(m, Machine)
    assert 0 <= m.battery_pct <= 100
    # A desktop reports no battery. That is a machine hibernating cannot save,
    # and the honest reading is "on mains", not an error.


def test_the_card_is_read_if_there_is_one(live):
    card = gpu()
    if card is None:
        pytest.skip("no nvidia-smi on this host")
    assert card.total_mb > 0
    assert 0 <= card.used_mb <= card.total_mb
    assert card.free_mb == card.total_mb - card.used_mb


def test_the_interpreter_install_path_is_not_a_classification_signal(live):
    # THE BUG THIS CAUGHT. Matching the raw command line classified every Python
    # process here as a download, because the interpreter lives under
    # ...\AppData\Roaming\uv\python\... and "\buv\b" matches inside a path.
    # It took 14 "expensive jobs" down to 3 once fixed.
    noise = Process(
        pid=1,
        name="python.exe",
        command=r"C:\Users\x\AppData\Roaming\uv\python\cpython-3.12\python.exe script.py",
    )
    assert noise.kind == OTHER

    real = Process(pid=2, name="uv.exe", command="uv pip install torch")
    assert real.kind == DOWNLOAD


def test_a_training_run_is_recognised_by_its_arguments():
    assert Process(pid=3, name="python.exe", command="python train_shr.py").kind == TRAINING
    assert Process(pid=4, name="python.exe", command="python -m pytest -q").kind == TRAINING


def test_the_signature_discards_the_executable_path():
    p = Process(pid=5, name="x", command=r'"C:\Program Files\ollama\ollama.exe" serve')
    assert p.signature == "ollama.exe serve"
    assert p.kind == DOWNLOAD


def test_expensive_work_is_a_small_fraction_of_what_is_running(live):
    found = jobs()
    assert len(found) < len(live) / 10  # most of a machine is not doing work worth saving


def test_it_never_plans_an_action_on_a_process_it_does_not_own(live):
    # THE FINDING. On this shared machine the expensive work belongs to other
    # sessions, so the custodian reports it and reaches for none of it.
    #
    # Note what this test caught about itself: run under pytest, `jobs()`
    # includes the pytest process, owned by this very run. So the assertion is
    # not "everything is someone else's" — it is the property that actually
    # matters, which holds either way.
    found = jobs()
    unowned = unowned_at_risk(found)
    assert unowned, "expected at least one job belonging to another session"

    actions = plan(Machine(on_mains=False, battery_pct=40, minutes_remaining=25), found)
    # Identity is the pid, never the name. Two sessions both run python.exe,
    # and this test failed on exactly that before Action carried a pid.
    touched = {a.pid for a in actions if a.pid is not None}
    for job in unowned:
        assert job.pid not in touched


def test_the_ollama_server_is_visible_and_untouchable(live):
    # Concrete: the model server holding 9 GB of this card was started by
    # another session. It is exactly what an outage would destroy, and exactly
    # what this custodian must not signal.
    found = jobs()
    theirs = {j.name for j in unowned_at_risk(found)}
    assert any("ollama" in name.lower() or "llama" in name.lower() for name in theirs)


def test_it_still_sleeps_what_it_does_own(live):
    # Displays are not a process. Losing mains always sleeps them.
    actions = plan(Machine(on_mains=False, battery_pct=90, minutes_remaining=60), jobs())
    assert any(a.target == "displays" for a in actions)


# --- The guarantee, proven over the space rather than observed once ----------
#
# Everything above reads this machine as it happens to be right now. That is the
# right way to catch what a fixture would hide — the `\buv\b` bug and the
# missing pid both came from it — but "3 of 3 jobs were another session's" is a
# snapshot, and a snapshot is not a guarantee. These generate the process table
# instead, and assert the invariant across every power state and job mix.


def _states(seed=0, cases=4000):
    """Machine states and job lists, generated rather than observed."""
    rng = random.Random(seed)
    kinds = (TRAINING, DOWNLOAD, OTHER)
    for _ in range(cases):
        machine = Machine(
            on_mains=rng.random() < 0.5,
            battery_pct=rng.randint(0, 100),
            minutes_remaining=rng.randint(0, 600),
        )
        jobs_ = [
            Job(
                pid=pid,
                name=rng.choice(["python.exe", "ollama.exe", "uv.exe", "node.exe"]),
                kind=rng.choice(kinds),
                owned=rng.random() < 0.5,
                resumable=rng.random() < 0.5,
                checkpointable=rng.random() < 0.5,
            )
            for pid in rng.sample(range(1, 10_000), rng.randint(0, 8))
        ]
        yield machine, jobs_


def test_no_plan_in_four_thousand_states_signals_an_unowned_process(live):
    # THE GUARANTEE. Not "on this machine today" — over 4,000 generated states
    # covering both power states, the full battery range and every mix of owned
    # and unowned work, no action is ever aimed at a pid we do not own.
    checked = 0
    for machine, jobs_ in _states():
        theirs = {j.pid for j in jobs_ if not j.owned}
        for action in plan(machine, jobs_):
            if action.pid is not None:
                assert action.pid not in theirs
                checked += 1
    assert checked > 1_000  # the invariant was actually exercised, not vacuous


def test_every_action_with_a_pid_names_a_job_that_exists():
    for machine, jobs_ in _states(seed=1):
        live = {j.pid for j in jobs_}
        for action in plan(machine, jobs_):
            if action.pid is not None:
                assert action.pid in live


def test_hibernate_is_the_one_action_that_reaches_another_session():
    # THE GAP the generated states exposed, which the live test could not.
    #
    # `plan` refuses to signal a process it does not own — and then hibernates
    # the whole machine, which suspends every process on it. Hibernation is not
    # a kill (Windows restores memory from disk), but a CUDA context does not
    # reliably survive it and an open socket does not survive it at all.
    #
    # The fix is not to refuse: losing mains on a flat battery ends that work
    # anyway, and unhibernated it ends worse. It is to say so.
    theirs = [Job(pid=99, name="ollama.exe", kind=TRAINING, owned=False, checkpointable=False)]
    flat = Machine(on_mains=False, battery_pct=5, minutes_remaining=3)
    (hibernate,) = [a for a in plan(flat, theirs) if a.verb == HIBERNATE]

    assert hibernate.pid is None  # it is not aimed at a process
    assert "another session" in hibernate.reason
    assert "ollama.exe(99)" in hibernate.reason

    # And it stays quiet when there is nothing of theirs to warn about.
    ours = [Job(pid=7, name="python.exe", kind=TRAINING, owned=True, checkpointable=True)]
    (mine,) = [a for a in plan(flat, ours) if a.verb == HIBERNATE]
    assert "another session" not in mine.reason


def test_collateral_is_reported_whenever_hibernate_is_planned():
    for machine, jobs_ in _states(seed=2):
        actions = plan(machine, jobs_)
        hibernates = [a for a in actions if a.verb == HIBERNATE]
        if not hibernates:
            continue
        expected = collateral(jobs_)
        reason = hibernates[0].reason
        assert ("another session" in reason) == bool(expected)
        for job in expected:
            assert f"{job.name}({job.pid})" in reason


def test_mains_restored_never_touches_their_work_either():
    for machine, jobs_ in _states(seed=3):
        if not machine.on_mains:
            continue
        theirs = {j.pid for j in jobs_ if not j.owned}
        for action in plan(machine, jobs_):
            assert action.pid not in theirs


# -- the power reading itself, not just its type -------------------------------


CSV_HEADER = '"EstimatedChargeRemaining","BatteryStatus","EstimatedRunTime"'


def _power_reading(monkeypatch, rows: list[str]):
    """`power()` over a crafted PowerShell response.

    `test_the_power_state_is_read_not_assumed` asserted `isinstance(m, Machine)` and
    `0 <= battery_pct <= 100` - both true for every possible reading, including an
    inverted one. Mutating `on_mains=status == 2` to `!=` inverts the AC-power state of
    the machine this product plans around, and the whole suite stayed green.

    The real battery cannot be made to report a chosen status, so the one layer below it
    is stubbed and the parsing and mapping are what get checked.
    """
    from powerguard import machine

    monkeypatch.setattr(machine, "_run", lambda *a, **k: chr(10).join(rows))
    return machine.power()


@pytest.mark.parametrize(
    "status,on_mains",
    [
        (2, True),  # 2 is "AC connected"; every other code is not
        (1, False),
        (3, False),
        (4, False),
        (5, False),
    ],
)
def test_only_battery_status_two_means_on_mains(monkeypatch, status, on_mains):
    reading = _power_reading(monkeypatch, [CSV_HEADER, f'"80","{status}","120"'])
    assert reading.on_mains is on_mains, status
    assert reading.battery_pct == 80
    assert reading.minutes_remaining == 120


@pytest.mark.parametrize(
    "pct,expected", [("-5", 0), ("0", 0), ("50", 50), ("100", 100), ("140", 100)]
)
def test_the_charge_is_clamped_to_a_percentage(monkeypatch, pct, expected):
    """A reading outside 0-100 is the sensor's problem, not a reason to plan on it."""
    assert (
        _power_reading(monkeypatch, [CSV_HEADER, f'"{pct}","2","60"']).battery_pct == expected
    )


def test_a_machine_with_no_battery_reads_as_on_mains(monkeypatch):
    """A desktop returns a header and no row. "On mains, 100%" is the honest reading;
    an error would stop a product whose whole job is deciding what to suspend."""
    reading = _power_reading(monkeypatch, [CSV_HEADER])
    assert (reading.on_mains, reading.battery_pct) == (True, 100)
    assert reading.minutes_remaining == 10_000


def test_an_unparseable_reading_falls_back_rather_than_raising(monkeypatch):
    reading = _power_reading(monkeypatch, [CSV_HEADER, '"not a number","x","y"'])
    assert (reading.on_mains, reading.battery_pct) == (True, 100)


def test_the_remaining_minutes_are_capped(monkeypatch):
    """Windows reports 71582788 minutes on mains, which is not a planning horizon."""
    assert (
        _power_reading(monkeypatch, [CSV_HEADER, '"100","2","71582788"']).minutes_remaining
        == 10_000
    )
