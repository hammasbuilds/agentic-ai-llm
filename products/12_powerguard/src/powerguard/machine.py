"""Reading this machine: power, GPU, and what is actually running on it.

No psutil, no wmi package. Everything here comes from tools the operating system
already ships, because a custodian that cannot start until a dependency resolves
is a custodian that is not running during the outage.

The important function is :func:`jobs`. It reports what is running *and whether
this process started it*, because the one rule that matters is that a custodian
never signals a process it does not own. Other sessions train on this box.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from .domain import DOWNLOAD, OTHER, TRAINING, Job, Machine

# Command lines that indicate expensive, interruptible work worth protecting.
#
# Matched against the executable's basename and the ARGUMENTS, never the whole
# command line. The first version matched the raw string and classified every
# Python process on this machine as a download, because the interpreter lives
# under `...\AppData\Roaming\uv\python\...` and `\buv\b` matches inside a path.
# A classifier that reads the interpreter's install location is reading noise.
# "train" is a prefix, not a whole word: train_shr.py and training.py are both
# training runs, and \btrain\b matches neither because _ and letters are word
# characters. The rest are whole words.
_TRAINING = re.compile(r"\b(train\w*|finetune|fine_tune|pytest|accelerate|torchrun)\b", re.I)
_DOWNLOAD = re.compile(r"\b(ollama|curl|wget|aria2c|hf_transfer|huggingface[-_]cli)\b", re.I)
_DOWNLOAD_ARG = re.compile(r"\b(pip|uv)\s+(install|pip|sync|add)\b", re.I)


def _run(args: list[str], timeout: float = 15.0) -> str:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


@dataclass(frozen=True)
class Gpu:
    name: str
    used_mb: int
    total_mb: int
    utilisation: int

    @property
    def free_mb(self) -> int:
        return self.total_mb - self.used_mb

    @property
    def busy(self) -> bool:
        return self.utilisation > 50


def gpu() -> Gpu | None:
    """The card, or None when there is not one to read."""
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    line = out.strip().splitlines()[0] if out.strip() else ""
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        return Gpu(parts[0], int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def power() -> Machine:
    """Mains, battery and estimated runtime.

    A desktop reports no battery, which is not an error: it is a machine that
    hibernating cannot save, and the honest reading is 100% on mains.
    """
    out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Battery | "
            "Select-Object -First 1 EstimatedChargeRemaining,BatteryStatus,"
            "EstimatedRunTime | ConvertTo-Csv -NoTypeInformation",
        ]
    )
    rows = [r for r in out.strip().splitlines() if r.strip()]
    if len(rows) < 2:
        return Machine(on_mains=True, battery_pct=100, minutes_remaining=10_000)
    values = [v.strip().strip('"') for v in rows[1].split(",")]
    try:
        pct = int(values[0] or 100)
        status = int(values[1] or 2)
        minutes = int(values[2] or 10_000)
    except (ValueError, IndexError):
        return Machine(on_mains=True, battery_pct=100, minutes_remaining=10_000)
    # BatteryStatus 2 means "AC connected".
    return Machine(
        on_mains=status == 2,
        battery_pct=max(0, min(100, pct)),
        minutes_remaining=min(minutes, 10_000),
    )


@dataclass
class Process:
    pid: int
    name: str
    command: str = ""
    owned: bool = False

    @property
    def signature(self) -> str:
        """Executable basename plus arguments, with the install path discarded."""
        command = (self.command or self.name).strip()
        if command.startswith('"'):
            head, _, tail = command[1:].partition('"')
        else:
            head, _, tail = command.partition(" ")
        # Split on EITHER separator, rather than on whatever the running interpreter
        # calls one. The separator in this string was chosen by the machine that
        # produced the command line - these are Windows command lines, with backslashes
        # - and `Path(head).name` asks the host instead: on Linux it finds no separator
        # in `C:\Program Files\ollama\ollama.exe` and returns the whole path as the
        # "basename", so the signature keeps the install path it exists to discard and
        # every rule matching on it misses.
        basename = re.split(r"[\\/]", head)[-1]
        return " ".join(f"{basename} {tail}".split())

    @property
    def kind(self) -> str:
        signature = self.signature
        if _TRAINING.search(signature):
            return TRAINING
        if _DOWNLOAD.search(signature) or _DOWNLOAD_ARG.search(signature):
            return DOWNLOAD
        return OTHER


def _own_tree() -> set[int]:
    """PIDs this process started, plus itself.

    Deliberately narrow. Anything not provably ours is not ours, and the cost of
    being wrong in the other direction is another session's training run.
    """
    mine = {os.getpid()}
    out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f'Get-CimInstance Win32_Process -Filter "ParentProcessId={os.getpid()}" | '
            "Select-Object ProcessId | ConvertTo-Csv -NoTypeInformation",
        ]
    )
    for row in out.strip().splitlines()[1:]:
        try:
            mine.add(int(row.strip().strip('"')))
        except ValueError:
            continue
    return mine


def processes(limit: int = 400) -> list[Process]:
    """Running processes, with command lines where the OS will give them."""
    out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine "
            "| ConvertTo-Csv -NoTypeInformation",
        ],
        timeout=40,
    )
    rows = out.strip().splitlines()
    if len(rows) < 2:
        return []
    mine = _own_tree()
    found: list[Process] = []
    for row in rows[1 : limit + 1]:
        parts = re.findall(r'"((?:[^"]|"")*)"', row)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[2].replace('""', '"') if len(parts) > 2 else ""
        found.append(Process(pid=pid, name=parts[1], command=command, owned=pid in mine))
    return found


def jobs() -> list[Job]:
    """Expensive work currently running, in the shape the planner takes."""
    return [
        Job(
            pid=p.pid,
            name=p.name,
            kind=p.kind,
            owned=p.owned,
            checkpointable=p.kind == TRAINING,
        )
        for p in processes()
        if p.kind != OTHER
    ]
