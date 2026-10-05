"""Render an audit. The compliance rate is deliberately hard to inflate."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .controls import CONTROLS, FAIL, INCONCLUSIVE, NOT_APPLICABLE, PASS, Result, run_all
from .evidence import Evidence, collect


@dataclass
class RepoAudit:
    name: str
    results: list[Result]

    @property
    def counted(self) -> list[Result]:
        return [r for r in self.results if r.counted]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == PASS)

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def rate(self) -> float:
        counted = self.counted
        return self.passed / len(counted) if counted else 0.0


@dataclass
class Audit:
    repos: list[RepoAudit] = field(default_factory=list)

    @property
    def totals(self) -> Counter:
        return Counter(r.status for repo in self.repos for r in repo.results)

    @property
    def counted(self) -> int:
        return sum(len(repo.counted) for repo in self.repos)

    @property
    def passed(self) -> int:
        return sum(repo.passed for repo in self.repos)

    @property
    def rate(self) -> float:
        """Pass rate over pass+fail only.

        Inconclusive and not-applicable are excluded rather than counted as
        passes. Counting them as passes is how an audit reports 90% when it
        measured a third of what it claimed to.
        """
        return self.passed / self.counted if self.counted else 0.0

    def by_control(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {c.id: [0, 0] for c in CONTROLS}
        for repo in self.repos:
            for result in repo.results:
                if not result.counted:
                    continue
                out[result.control][1] += 1
                if result.status == PASS:
                    out[result.control][0] += 1
        return {k: (v[0], v[1]) for k, v in out.items() if v[1]}


def audit_folder(parent: Path, skip_prefixes: tuple[str, ...] = (".", "_")) -> Audit:
    audit = Audit()
    for directory in sorted(parent.iterdir()):
        if not directory.is_dir() or directory.name.startswith(skip_prefixes):
            continue
        evidence = collect(directory)
        if not evidence.python_files and evidence.readme is None:
            continue  # not a project, just a folder
        audit.repos.append(RepoAudit(directory.name, run_all(evidence)))
    return audit


def audit_one(root: Path) -> tuple[Evidence, RepoAudit]:
    evidence = collect(root)
    return evidence, RepoAudit(evidence.name, run_all(evidence))


_SYMBOL = {PASS: "ok  ", FAIL: "FAIL", INCONCLUSIVE: "??  ", NOT_APPLICABLE: "-   "}


def render_repo(repo: RepoAudit) -> str:
    policies = {c.id: c.policy for c in CONTROLS}
    out = [
        "=" * 78,
        f"  {repo.name}  -  {repo.passed}/{len(repo.counted)} ({repo.rate:.0%})",
        "=" * 78,
        "",
    ]
    for result in repo.results:
        out.append(f"  [{_SYMBOL[result.status]}] {result.control}")
        out.append(f"          policy: {policies.get(result.control, '')}")
        out.append(f"          found : {result.detail}")
        if result.artefact:
            out.append(f"          in    : {result.artefact}")
    out.append("")
    out.append("=" * 78)
    return "\n".join(out)


def render_folder(audit: Audit) -> str:
    out = [
        "=" * 78,
        f"  {len(audit.repos)} repositories  -  "
        f"{audit.passed}/{audit.counted} controls passed ({audit.rate:.0%})",
        "=" * 78,
        "",
    ]

    totals = audit.totals
    out.append(
        f"  pass {totals[PASS]}   fail {totals[FAIL]}   "
        f"inconclusive {totals[INCONCLUSIVE]}   n/a {totals[NOT_APPLICABLE]}"
    )
    out.append("  Inconclusive and n/a are excluded from the rate, never counted as passes.")
    out.append("")

    out.append("  BY CONTROL")
    policies = {c.id: c.policy for c in CONTROLS}
    for control, (passed, total) in sorted(
        audit.by_control().items(), key=lambda kv: kv[1][0] / kv[1][1]
    ):
        out.append(f"    {passed:3d}/{total:<3d} {passed / total:4.0%}  {control}")
        out.append(f"               {policies[control]}")
    out.append("")

    worst = sorted(audit.repos, key=lambda r: r.rate)[:8]
    out.append("  LOWEST-SCORING REPOSITORIES")
    for repo in worst:
        names = ", ".join(r.control for r in repo.failures[:4])
        out.append(f"    {repo.rate:4.0%}  {repo.name:28s} {names}")
    out.append("")
    out.append("=" * 78)
    return "\n".join(out)


def to_json(audit: Audit) -> str:
    return json.dumps(
        {
            "repositories": len(audit.repos),
            "controls_passed": audit.passed,
            "controls_counted": audit.counted,
            "rate": round(audit.rate, 4),
            "by_control": {
                k: {"passed": p, "of": t} for k, (p, t) in audit.by_control().items()
            },
            "repos": [
                {
                    "name": repo.name,
                    "rate": round(repo.rate, 4),
                    "results": [asdict(r) for r in repo.results],
                }
                for repo in audit.repos
            ],
        },
        indent=2,
    )
