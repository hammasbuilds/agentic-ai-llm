"""Write a committed repository listing into `data/trees`.

The regeneration path `data/trees/README.md` describes. `apps/_engine/trees.fetch` and
`trees.fetch_at_commit` do the work and nothing called either of them: a check that
resolves references through the import graph found both named only in two module
docstrings which list them among the functions that "had no caller anywhere in the
repository" and present them as revived. They were not, so the note telling a reader
how to refresh a listing described something that could not happen.

This is the entry point, and it is deliberately not called from the evaluation path.
Fetching needs the GitHub API, and a measurement that silently reaches the network
when a file is missing is a measurement whose result depends on whether the network
was there - which is the opposite of what committing these listings is for. A listing
is refreshed on purpose, by running this.

    python scripts/fetch_trees.py --repo django/django
    python scripts/fetch_trees.py --repo scikit-learn/scikit-learn \
        --commit 1e8a5b833d1b58f3ab84099c4582239af854b23a
    python scripts/fetch_trees.py --missing      # every listing a scored instance needs and lacks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps._engine import trees  # noqa: E402


def _one(repo: str, ref: str, commit: str | None, force: bool) -> int:
    if commit:
        paths = trees.fetch_at_commit(repo, commit)
        if paths is None:
            print(f"could not fetch {repo} at {commit[:12]}", file=sys.stderr)
            return 1
        print(f"{repo}@{commit[:12]}: {len(paths):,} paths")
        return 0
    paths = trees.fetch(repo, ref, force=force)
    print(f"{repo}@{ref}: {len(paths):,} paths")
    return 0


def _missing() -> int:
    """Every listing a scored SWE-bench instance needs and the repository lacks.

    Read from the committed slice, so this says what is missing without fetching
    anything first.
    """
    from apps._engine import swebench_data

    instances = swebench_data.load()
    have = trees.commit_listings()
    repos = trees.cached_repos()
    wanted = {
        (inst.repo, inst.base_commit)
        for inst in instances
        if (inst.repo, inst.base_commit[:12]) not in have and inst.repo not in repos
    }
    if not wanted:
        print(f"nothing missing: {len(instances)} instances, {len(repos)} repo listings")
        return 0
    print(f"{len(wanted)} listing(s) missing:")
    failed = 0
    for repo, commit in sorted(wanted):
        if trees.fetch_at_commit(repo, commit) is None:
            print(f"  FAILED {repo}@{commit[:12]}", file=sys.stderr)
            failed += 1
        else:
            print(f"  wrote  {repo}@{commit[:12]}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", help="owner/name, e.g. django/django")
    parser.add_argument("--ref", default="HEAD", help="branch or tag for a repo-level listing")
    parser.add_argument("--commit", help="write a listing at this exact commit instead")
    parser.add_argument(
        "--force", action="store_true", help="refetch a listing that is already committed"
    )
    parser.add_argument(
        "--missing",
        action="store_true",
        help="write every listing a scored instance needs and this repository lacks",
    )
    args = parser.parse_args(argv)

    if args.missing:
        if args.repo:
            print("--missing takes no --repo", file=sys.stderr)
            return 2
        return _missing()
    if not args.repo:
        print("pass --repo owner/name, or --missing", file=sys.stderr)
        return 2
    return _one(args.repo, args.ref, args.commit, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
