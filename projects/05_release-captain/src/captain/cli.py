"""Command line for release-captain. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .gate import evaluate, render
from .history import NotAGitRepository, is_repository, read_history
from .risk import Baseline, rank_by, rank_disagreement, score_commit


class FolderError(ValueError):
    """The folder argument is not a folder, or is not there."""


def _folder(raw: str) -> Path:
    """A path that must be a directory of checkouts.

    `Path(raw).resolve()` then `iterdir()` raised `NotADirectoryError` straight out of
    `main()` for the commonest mistake there is - giving a file where a folder was
    wanted - and a path that does not exist at all gave `FileNotFoundError`. Both are
    the caller's argument, and neither deserves a stack trace naming this module's
    `iterdir`.
    """
    path = Path(raw).resolve()
    if not path.exists():
        raise FolderError(f"no such path: {path}")
    if not path.is_dir():
        raise FolderError(f"{path} is a file; this command takes a folder of checkouts")
    return path


def _gate_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    try:
        history = read_history(repo, limit=args.scan)
    except NotAGitRepository as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = evaluate(history, since=args.since)
    print(render(result))

    if args.json:
        payload = {
            "repo": result.repo,
            "verdict": result.verdict,
            "blocked": result.blocked,
            "commits_considered": result.commits_considered,
            "checks": [asdict(c) for c in result.checks],
            "riskiest": [
                {
                    "sha": c.sha,
                    "subject": c.subject,
                    "score": s,
                    "churn": c.churn,
                    "files": len(c.files),
                    "spread": c.spread,
                    "touches_tests": c.touches_tests,
                }
                for c, s in result.riskiest
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if (result.blocked and args.strict) else 0


def _explain_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    history = read_history(repo)
    baseline = Baseline.from_history(history)
    match = [c for c in history.commits if c.sha.startswith(args.sha)]
    if not match:
        print(f"no commit starting {args.sha!r}", file=sys.stderr)
        return 1
    commit = match[0]
    factors = score_commit(commit, baseline)
    print(f"{commit.sha[:10]}  {commit.subject}")
    print(
        f"  {commit.churn} lines, {len(commit.files)} files, "
        f"{commit.spread} areas, tests {'yes' if commit.touches_tests else 'NO'}"
    )
    print(f"  risk {factors.score()}")
    print()
    print(f"  {'factor':10s} {'raw':>6s} {'points':>7s}")
    for name, raw, points in factors.explain():
        print(f"  {name:10s} {raw:6.2f} {points:7.1f}")
    return 0


def _compare_command(args: argparse.Namespace) -> int:
    """Do the single metrics rank the same commits as risky?

    Raw top-N overlap is confounded: with 8 commits and a top-5 list, chance
    alone gives 62%. The excess over chance is the only readable number.
    """
    parent = _folder(args.parent)
    rows = []
    for d in sorted(parent.iterdir()):
        if not d.is_dir() or not is_repository(d):
            continue
        try:
            history = read_history(d)
        except NotAGitRepository:
            continue
        n = len(history.commits)
        if n < args.min_commits:
            continue
        top = min(args.top, n)
        chance = top / n
        dis = rank_disagreement(history, top=top)
        if dis:
            rows.append((d.name, n, chance, dis))

    if not rows:
        print("no repositories with enough history")
        return 0

    print(f"{'repo':26s} {'n':>3s} {'chance':>7s} {'c/f':>6s} {'c/s':>6s} {'f/s':>6s}")
    print("-" * 62)
    for name, n, chance, dis in sorted(rows, key=lambda r: -r[1]):
        print(
            f"{name:26s} {n:3d} {chance:7.0%} "
            f"{dis['churn vs files']:6.0%} {dis['churn vs spread']:6.0%} "
            f"{dis['files vs spread']:6.0%}"
        )

    print("-" * 62)
    for key in ("churn vs files", "churn vs spread", "files vs spread"):
        excess = [dis[key] - chance for _, _, chance, dis in rows]
        print(f"{key:18s} mean excess over chance = {sum(excess) / len(excess):+.0%}")
    return 0


def _sweep_command(args: argparse.Namespace) -> int:
    """Gate every checkout under a folder and print the verdict distribution.

    The README quoted this table across a chosen 28 repositories, and no command
    here produced it. A chosen subset and a folder are different populations: run
    over the folder, the share of clean GO verdicts is a fraction of what the
    subset suggested, and most of the ones that remain rest on a check that had
    nothing to look at.
    """
    parent = _folder(args.parent)
    verdicts: dict[str, list[str]] = {"GO": [], "GO WITH WARNINGS": [], "NO-GO": []}
    unmeasured: list[str] = []
    blocked_by: dict[str, int] = {}
    skipped = 0
    for d in sorted(parent.iterdir()):
        if not d.is_dir() or not is_repository(d):
            continue
        try:
            history = read_history(d, limit=args.scan)
        except NotAGitRepository:
            continue
        if not history.commits:
            skipped += 1
            continue
        result = evaluate(history, since=args.since)
        verdicts[result.verdict].append(d.name)
        if result.verdict == "GO" and result.not_measured:
            unmeasured.append(d.name)
        for check in result.blockers:
            blocked_by[check.name] = blocked_by.get(check.name, 0) + 1

    total = sum(len(v) for v in verdicts.values())
    print(f"{'Verdict':20s} {'Repositories':>12s}")
    print("-" * 34)
    for name, repos in verdicts.items():
        print(f"{name:20s} {len(repos):12d}")
    print("-" * 34)
    print(f"{'measured':20s} {total:12d}")
    print()
    print(
        f"{len(unmeasured)} of the {len(verdicts['GO'])} clean GO verdict(s) rest on a check "
        "that had nothing to look at"
    )
    for name in unmeasured:
        print(f"    {name}")
    if blocked_by:
        print("\nWhat blocked the NO-GO repositories:")
        for name, count in sorted(blocked_by.items(), key=lambda kv: -kv[1]):
            print(f"    {count:3d}  {name}")
    if skipped:
        print(f"\n{skipped} checkout(s) had no commits in range and were not counted")
    return 0


def _extremes_command(args: argparse.Namespace) -> int:
    """The widest and the longest commit in a folder of checkouts, and their ratios.

    The README's headline is this: "the commit that changed the most lines changed
    196,743 of them in 11 files. The commit that reached the most files changed 510
    lines across 1,809." No command here computed it - `gate`, `explain`, `rank`,
    `sweep` and `compare` are all per-repository - so the figure had no producer in the
    tool that is supposed to produce it, and it was wrong: the real maximum by lines is
    larger, and in a repository the stated population left out.

    Every checkout under the folder, including the one this tool ships in. A survey that
    excludes its own repository is choosing its population.
    """
    parent = _folder(args.parent)
    by_lines: tuple[int, int, str, str, str] | None = None
    by_files: tuple[int, int, str, str, str] | None = None
    looked_at = 0
    no_history = 0

    for d in sorted(parent.iterdir()):
        if not d.is_dir() or not is_repository(d):
            continue
        try:
            history = read_history(d, limit=args.scan)
        except NotAGitRepository:
            continue
        if not history.commits:
            no_history += 1
            continue
        looked_at += 1
        for commit in history.commits:
            row = (commit.churn, len(commit.files), d.name, commit.sha[:8], commit.subject[:44])
            if by_lines is None or commit.churn > by_lines[0]:
                by_lines = row
            if by_files is None or len(commit.files) > by_files[1]:
                by_files = row

    if by_lines is None or by_files is None:
        print(f"no checkout under {parent} has any history", file=sys.stderr)
        return 2

    print(f"{looked_at} repositories with history under {parent}")
    print()
    for label, row in (("most lines", by_lines), ("most files", by_files)):
        churn, files, repo, sha, subject = row
        print(f"  {label:10s} {churn:>9,d} lines  {files:>6,d} files  {repo}/{sha}  {subject}")
    print()
    # The ratio each way, which is the point of printing both: a single-number metric
    # ranks one of these two wrongly, and how wrongly is the number worth quoting.
    print(
        f"  by lines, the first is {by_lines[0] / max(by_files[0], 1):.0f} times the second; "
        f"by files, the second is {by_files[1] / max(by_lines[1], 1):.0f} times the first"
    )
    if no_history:
        print()
        print(f"{no_history} checkout(s) had no commits in range and were not counted")
    return 0


def _rank_command(args: argparse.Namespace) -> int:
    history = read_history(Path(args.repo).resolve())
    baseline = Baseline.from_history(history)
    for commit in rank_by(history, args.by)[: args.top]:
        score = score_commit(commit, baseline).score()
        print(
            f"  {score:5.1f}  {commit.sha[:8]}  {commit.churn:7d}L "
            f"{len(commit.files):4d}f {commit.spread}dir  {commit.subject[:48]}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="captain",
        description="Release readiness from diff statistics, not from opinion.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gate", help="go / no-go for a release")
    g.add_argument("repo")
    g.add_argument("--since", type=int, default=None, help="assess the last N commits")
    g.add_argument("--scan", type=int, default=None, help="read at most N commits of history")
    g.add_argument("--json", help="also write the decision as JSON")
    g.add_argument("--strict", action="store_true", help="exit 1 when blocked, for CI")
    g.set_defaults(func=_gate_command)

    e = sub.add_parser("explain", help="why one commit scored what it did")
    e.add_argument("repo")
    e.add_argument("sha")
    e.set_defaults(func=_explain_command)

    r = sub.add_parser("rank", help="rank commits by one metric")
    r.add_argument("repo")
    r.add_argument("--by", choices=["churn", "files", "spread", "risk"], default="risk")
    r.add_argument("--top", type=int, default=10)
    r.set_defaults(func=_rank_command)

    w = sub.add_parser("sweep", help="gate every checkout under a folder")
    w.add_argument("parent")
    w.add_argument("--since", type=int, default=None, help="assess the last N commits")
    w.add_argument("--scan", type=int, default=None, help="read at most N commits of history")
    w.set_defaults(func=_sweep_command)

    x = sub.add_parser("extremes", help="the longest and widest commit in a folder")
    x.add_argument("parent")
    x.add_argument("--scan", type=int, default=400)
    x.set_defaults(func=_extremes_command)

    c = sub.add_parser("compare", help="do single metrics agree, above chance?")
    c.add_argument("parent")
    c.add_argument("--top", type=int, default=5)
    c.add_argument("--min-commits", type=int, default=8)
    c.set_defaults(func=_compare_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FolderError as bad:
        print(f"{bad}", file=sys.stderr)
        return 2
    except NotAGitRepository as bad:
        # `gate` caught this and returned 2; `rank`, `explain` and `extremes` did not,
        # so the same mistake was a readable message from one subcommand and a stack
        # trace from the next. Handled here so every subcommand answers the same way.
        print(f"{bad}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
