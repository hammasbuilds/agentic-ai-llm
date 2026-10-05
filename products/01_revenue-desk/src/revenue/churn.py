"""Measuring reverts in real edit history.

This product's finding is how often one writer's update destroys another's
recent correction. A CRM with agents writing into it is the setting; the
mechanism is general, and there is a large, real, dated corpus of exactly that
mechanism on any developer's disk: the git history of a folder of repositories.

A revert here is a line that went A, then B, then back to A. That is not churn
and not a rewrite — it is one edit undoing another, which is precisely the event
`domain.detect_reverts` looks for on a deal record.

Reading real history rather than inventing a CRM log means the rate is a
property of how editing actually goes, not of how a fixture was written.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# The folder whose git checkouts are surveyed. Set REPOS_ROOT to point it
# elsewhere; the default is ~/code.
REPOS = Path(os.environ.get("REPOS_ROOT") or Path.home() / "code").expanduser()

# Files a person does not write line by line. A committed dataset or a
# regenerated result file produces enormous numbers of "edits" that were never
# anybody's judgement, and both ends of that distort the rate: the datasets
# inflate the denominator, the result files inflate the numerator.
DATA_SUFFIXES = frozenset(
    {".csv", ".tsv", ".txt", ".log", ".gb", ".jsonl", ".lock", ".parquet", ".arrow"}
)
_GENERATED = re.compile(
    r"(^|/)results/|(^|/)(results?|runs|served|outputs?|metrics)[^/]*\.json$",
    re.I,
)


class NoHistoryError(RuntimeError):
    """The repository has no readable history."""


def is_authored(path: str) -> bool:
    """Whether a person wrote this file line by line.

    The distinction is the whole measurement. A `results.json` rewritten by a
    re-run is a machine re-emitting its own output, and a line returning to a
    previous value there is not one writer undoing another — it is the same
    script producing the same number twice.
    """
    if _GENERATED.search(path):
        return False
    dot = path.rfind(".")
    return dot < 0 or path[dot:].lower() not in DATA_SUFFIXES


@dataclass(frozen=True)
class Edit:
    """One change to one line of one file."""

    commit: str
    seq: int
    path: str
    line: str
    added: bool

    @property
    def authored(self) -> bool:
        return is_authored(self.path)


@dataclass
class Revert:
    path: str
    line: str
    first_seen: int
    removed_at: int
    restored_at: int

    @property
    def gap(self) -> int:
        """Commits between the removal and the restoration."""
        return self.restored_at - self.removed_at


@dataclass
class Summary:
    repo: str
    commits: int = 0
    edits: int = 0
    reverts: list = field(default_factory=list)
    authored_edits: int = 0
    authored_reverts: list = field(default_factory=list)

    @property
    def revert_rate(self) -> float:
        """Over everything in the history, generated files included."""
        return len(self.reverts) / self.edits if self.edits else 0.0

    @property
    def authored_rate(self) -> float:
        """Over lines a person actually wrote. The honest one."""
        if not self.authored_edits:
            return 0.0
        return len(self.authored_reverts) / self.authored_edits


def _git(repo: Path, *args: str, timeout: float = 180.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NoHistoryError(f"{repo}: {exc}") from exc
    return proc.stdout


def edits(repo: Path, limit: int = 200) -> list[Edit]:
    """Line-level additions and removals, oldest commit first.

    Whitespace-only and pure-move changes are excluded by asking git to ignore
    them: a line reindented is not a correction being undone.
    """
    raw = _git(
        repo,
        "log",
        "--reverse",
        f"-n{limit}",
        "--format=__commit__ %h",
        "-U0",
        "--no-renames",
        "-w",
        "--ignore-blank-lines",
        "-p",
    )
    if not raw.strip():
        raise NoHistoryError(f"{repo} has no history")

    out: list[Edit] = []
    commit = ""
    path = ""
    seq = -1
    for line in raw.splitlines():
        if line.startswith("__commit__ "):
            commit = line.split(" ", 1)[1].strip()
            seq += 1
        elif line.startswith("+++ b/"):
            path = line[6:].strip()
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            body = line[1:].strip()
            if len(body) < 8:
                continue  # a brace or a comma is not a correction
            out.append(Edit(commit, seq, path, body, added=line.startswith("+")))
    return out


MIN_MEANINGFUL = 8


def find_reverts(history: list[Edit]) -> list[Revert]:
    """Lines that were removed and later restored verbatim.

    Keyed on (file, exact line). Requiring the text to come back identically is
    strict on purpose: anything looser measures rewriting rather than undoing.

    Trivially short lines are skipped here rather than only at parse time. A
    closing brace reappearing is not a judgement being undone, and that is a
    property of what counts as a revert — it should hold for any caller, not
    only for edits this module happened to read out of git.

    Within a single commit a line can be both removed and added — it moved, or
    the same text appears in two hunks. With ``-U0`` git reports that as a pair,
    and reading it as a revert was 86% of everything this found. Undoing is a
    relationship *between* commits, so same-commit pairs cancel and the three
    events must land on three increasing commits.
    """
    per_commit: dict[tuple[str, str], dict[int, set[bool]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for edit in history:
        if len(edit.line.strip()) < MIN_MEANINGFUL:
            continue
        per_commit[(edit.path, edit.line)][edit.seq].add(edit.added)

    found: list[Revert] = []
    for (path, line), commits in per_commit.items():
        # A commit that both adds and removes the line did neither: net zero.
        events = sorted(
            (seq, next(iter(kinds)))
            for seq, kinds in commits.items()
            if len(kinds) == 1
        )
        first = None
        removed = None
        for seq, added in events:
            if added and first is None:
                first = seq
            elif not added and first is not None and removed is None:
                removed = seq
            elif added and removed is not None:
                found.append(Revert(path, line, first, removed, seq))
                removed = None
    return found


@lru_cache(maxsize=2)
def survey(
    root: str | None = None, repos: int = 0, limit: int = 10_000
) -> tuple[Summary, ...]:
    """Every repository under ``root`` with history, summarised.

    ``repos`` defaults to no cap. It used to default to 12, which stopped
    alphabetically after a third of the checkouts and — because a revert is a
    *pair* of edits drawn from the history pool — could only undercount. It did:
    12 repositories reported 0.063%, all 35 report 0.285%.
    """
    base = Path(root) if root else REPOS
    out: list[Summary] = []
    for path in sorted(p for p in base.iterdir() if p.is_dir()):
        if path.name.startswith((".", "_")) or not (path / ".git").exists():
            continue
        try:
            history = edits(path, limit=limit)
        except NoHistoryError:
            continue
        if not history:
            continue
        authored = [e for e in history if e.authored]
        out.append(
            Summary(
                repo=path.name,
                commits=len({e.commit for e in history}),
                edits=len(history),
                reverts=find_reverts(history),
                authored_edits=len(authored),
                authored_reverts=find_reverts(authored),
            )
        )
        if repos and len(out) >= repos:
            break
    return tuple(out)
