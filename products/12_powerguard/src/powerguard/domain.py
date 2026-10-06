"""What to do when the power goes, and what this process is allowed to touch.

The ownership rule is the important one. Other sessions train on this machine,
and a custodian that signals a PID it did not start is worse than no custodian.
"""

from __future__ import annotations

from dataclasses import dataclass

TRAINING = "training"
DOWNLOAD = "download"
OTHER = "other"

CHECKPOINT = "checkpoint"
PAUSE = "pause"
SLEEP_DISPLAYS = "sleep-displays"
HIBERNATE = "hibernate"
RESUME = "resume"

# Targets that are not processes and therefore carry no pid.
_NOT_A_PROCESS = frozenset({"displays", "system"})


@dataclass(frozen=True)
class Job:
    pid: int
    name: str
    kind: str
    owned: bool  # started by this custodian
    checkpointable: bool = False
    resumable: bool = True


@dataclass(frozen=True)
class Machine:
    on_mains: bool
    battery_pct: int
    minutes_remaining: int

    def __post_init__(self) -> None:
        if not 0 <= self.battery_pct <= 100:
            raise ValueError("battery_pct must be a percentage")


@dataclass(frozen=True)
class Thresholds:
    hibernate_below_pct: int = 20
    hibernate_below_minutes: int = 5
    resume_above_pct: int = 35  # hysteresis: not the same line as hibernate

    def __post_init__(self) -> None:
        if self.resume_above_pct <= self.hibernate_below_pct:
            raise ValueError(
                "resume must sit above hibernate, or a flapping supply produces "
                "one action per flap"
            )


@dataclass(frozen=True)
class Action:
    """One thing to do, and to exactly one process.

    ``pid`` is the identity; ``target`` is only a label for a person reading the
    log. Identifying a process by name is how a custodian signals the wrong one:
    on a shared machine two sessions both run ``python.exe``, and "checkpoint
    python.exe" is an instruction that cannot be carried out safely. This
    product's own test against the real process table caught that.
    """

    verb: str
    target: str
    reason: str
    pid: int | None = None

    def __post_init__(self) -> None:
        if self.pid is None and self.target not in _NOT_A_PROCESS:
            raise ValueError(
                f"{self.verb} on {self.target!r} has no pid; a name is not an identity"
            )


# Cheapest to lose, last to be saved.
_COST = {TRAINING: 0, DOWNLOAD: 1, OTHER: 2}


def unowned_at_risk(jobs: list[Job]) -> list[Job]:
    """Jobs this custodian must not touch, and cannot protect.

    Surfaced so a person can act, never signalled. Another session's training
    run is not ours to stop.
    """
    return [j for j in jobs if not j.owned and j.kind in (TRAINING, DOWNLOAD)]


def collateral(jobs: list[Job]) -> list[Job]:
    """Unowned work that hibernating the system would suspend anyway.

    The per-process guarantee — never signal a process we do not own — is real
    and it is not the whole story. `hibernate` has no pid because it is not
    aimed at a process; it stops every process on the machine, ours and theirs,
    and no ownership check applies to it.

    Hibernation is not a kill: Windows writes memory to disk and processes
    resume. But a CUDA context does not reliably survive it and an open socket
    does not survive it at all, so another session's training run or download is
    genuinely at risk from an action this custodian took.

    The honest response is not to refuse — losing mains with a flat battery ends
    that work regardless, and unhibernated it ends worse. It is to say so, which
    is what `plan` puts in the hibernate action's reason.
    """
    return unowned_at_risk(jobs)


def plan(
    machine: Machine,
    jobs: list[Job],
    thresholds: Thresholds | None = None,
) -> list[Action]:
    """The ordered list of actions for the current power state."""
    t = thresholds or Thresholds()
    if machine.on_mains:
        return (
            [
                Action(RESUME, j.name, "mains restored, battery above the resume line", j.pid)
                for j in jobs
                if j.owned and j.resumable
            ]
            if machine.battery_pct >= t.resume_above_pct
            else []
        )

    actions: list[Action] = []
    for job in sorted(jobs, key=lambda j: (_COST.get(j.kind, 9), j.pid)):
        if not job.owned:
            continue
        if job.kind == TRAINING and job.checkpointable:
            actions.append(
                Action(CHECKPOINT, job.name, "mains lost; an epoch is expensive", job.pid)
            )
        elif job.kind == DOWNLOAD:
            actions.append(
                Action(
                    PAUSE,
                    job.name,
                    "mains lost; a partial transfer resumes, a dead one does not",
                    job.pid,
                )
            )

    actions.append(Action(SLEEP_DISPLAYS, "displays", "nothing is being watched on battery"))

    flat = machine.battery_pct <= t.hibernate_below_pct
    brief = machine.minutes_remaining <= t.hibernate_below_minutes
    if flat or brief:
        reason = f"battery {machine.battery_pct}%, {machine.minutes_remaining} min left"
        # The one action with no pid and machine-wide reach. Everything else
        # here is refused on a process we do not own; this is not, so it names
        # what it will take down with it rather than presenting itself as safe.
        others = collateral(jobs)
        if others:
            named = ", ".join(f"{j.name}({j.pid})" for j in sorted(others, key=lambda j: j.pid))
            reason += f"; SUSPENDS {len(others)} job(s) belonging to another session: {named}"
        actions.append(Action(HIBERNATE, "system", reason))
    return actions


def work_lost(gpu_hours: float, transferred_mb: int) -> dict:
    """The per-outage cost, for the before-and-after table."""
    if gpu_hours < 0 or transferred_mb < 0:
        raise ValueError("an outage cannot return work")
    return {"gpu_hours": round(gpu_hours, 2), "transferred_mb": transferred_mb}
