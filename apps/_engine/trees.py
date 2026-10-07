"""Repository file listings, fetched once per repo and cached on disk.

Phase 2 needs a candidate set: the files a retriever is allowed to choose from. The
gold patch names the answer but not the alternatives, so the file list has to come
from somewhere, and the Trees API gives it as paths only - no blobs, no clone.

**One tree per repository, not one per instance.** The 300 instances span 297 distinct
base commits, and fetching a tree for each would mean 297 multi-megabyte responses. A
repository's *file paths* barely move between commits, so one listing per repo covers
every instance in it. That approximation is not free, and `coverage()` measures what it
costs: the fraction of instances whose gold file is missing from the listing. Anything
missing is counted as an automatic retrieval failure rather than quietly dropped, so the
scores in Phase 2 are pessimistic by exactly that amount, never optimistic.

The fallback path exists because the network here kills large responses mid-transfer.
A recursive fetch of django/django is ~2 MB and dies; the same tree walked one
top-level subtree at a time arrives in pieces small enough to survive.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import time
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "data" / "trees"

# Source files a fix could plausibly land in. Excluding everything else keeps the
# candidate set honest: a retriever should not get credit for ranking above a .png.
SOURCE_SUFFIXES = (".py", ".pyx", ".pxd")


def _gh(path: str, timeout: int = 180) -> dict | None:
    """One Trees API call. Returns None on any failure, including a killed transfer."""
    try:
        r = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        # A transfer cut short mid-JSON looks exactly like this.
        return None


def _fetch_recursive(repo: str, ref: str) -> list[str] | None:
    data = _gh(f"repos/{repo}/git/trees/{ref}?recursive=1")
    if data is None or "tree" not in data:
        return None
    if data.get("truncated"):
        # >100k entries. The API silently drops the rest, so the listing would be a
        # lie; fall back to walking, which fetches each subtree under its own limit.
        return None
    return [e["path"] for e in data["tree"] if e["type"] == "blob"]


def _fetch_walked(repo: str, ref: str) -> list[str] | None:
    """Root listing, then one recursive call per top-level subtree.

    Slower in calls but each response is a fraction of the size, which is what makes
    it work on a connection that drops large ones.
    """
    root = _gh(f"repos/{repo}/git/trees/{ref}")
    if root is None or "tree" not in root:
        return None

    paths: list[str] = []
    for entry in root["tree"]:
        if entry["type"] == "blob":
            paths.append(entry["path"])
            continue
        sub = None
        for attempt in range(3):
            sub = _gh(f"repos/{repo}/git/trees/{entry['sha']}?recursive=1")
            if sub is not None:
                break
            time.sleep(2 * (attempt + 1))
        if sub is None:
            # One unreachable subtree makes the listing incomplete, and an incomplete
            # listing silently lowers every score computed from it. Fail loudly.
            return None
        prefix = entry["path"]
        paths.extend(f"{prefix}/{e['path']}" for e in sub.get("tree", []) if e["type"] == "blob")
    return paths


def fetch(repo: str, ref: str, *, force: bool = False) -> list[str]:
    """All blob paths in `repo` at `ref`, cached on disk after the first success."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{repo.replace('/', '__')}.json.gz"

    if cache_file.exists() and not force:
        with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
            return json.load(fh)["paths"]

    paths = _fetch_recursive(repo, ref)
    how = "recursive"
    if paths is None:
        paths = _fetch_walked(repo, ref)
        how = "walked"
    if paths is None:
        raise RuntimeError(f"could not fetch tree for {repo}@{ref[:10]}")

    with gzip.open(cache_file, "wt", encoding="utf-8") as fh:
        json.dump({"repo": repo, "ref": ref, "how": how, "paths": paths}, fh)
    return paths


def source_files(paths: list[str]) -> list[str]:
    return [p for p in paths if p.endswith(SOURCE_SUFFIXES)]


def fetch_at_commit(repo: str, commit: str) -> list[str] | None:
    """A listing for one exact commit, cached separately from the repo-level one.

    Used only where the approximation demonstrably fails. scikit-learn moved most of
    its modules behind underscore names (`encoders.py` -> `_encoders.py`), so a listing
    taken at one commit is missing a third of its gold files at others. Repairing just
    those instances costs a handful of requests and removes an automatic-miss floor
    that would otherwise sit under every score.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"at__{repo.replace('/', '__')}__{commit[:12]}.json.gz"
    if cache_file.exists():
        with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
            return json.load(fh)["paths"]

    paths = _fetch_recursive(repo, commit) or _fetch_walked(repo, commit)
    if paths is None:
        return None
    with gzip.open(cache_file, "wt", encoding="utf-8") as fh:
        json.dump({"repo": repo, "ref": commit, "how": "at_commit", "paths": paths}, fh)
    return paths


def commit_listings() -> dict[tuple[str, str], list[str]]:
    """Every per-commit listing on disk, keyed by (repo, commit-prefix)."""
    out: dict[tuple[str, str], list[str]] = {}
    if not CACHE.exists():
        return out
    for f in sorted(CACHE.glob("at__*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
        out[(blob["repo"], blob["ref"][:12])] = blob["paths"]
    return out


def listing_for(inst, repo_listings: dict, commit_listings_: dict) -> list[str]:
    """The candidate set for one instance: its exact commit if we have it, else the repo."""
    exact = commit_listings_.get((inst.repo, inst.base_commit[:12]))
    return exact if exact is not None else repo_listings.get(inst.repo, [])


def cached_repos() -> dict[str, list[str]]:
    """Every repo-level listing on disk, keyed by repo name.

    `at__*` files are per-commit listings for the handful of instances the repo-level
    approximation missed. They carry the same `repo` field, so globbing `*.json.gz`
    lets one of them overwrite the repository listing it was meant to supplement -
    silently narrowing the candidate set for every other instance in that repo.
    """
    out: dict[str, list[str]] = {}
    if not CACHE.exists():
        return out
    for f in sorted(CACHE.glob("*.json.gz")):
        if f.name.startswith("at__"):
            continue
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
        out[blob["repo"]] = blob["paths"]
    return out


def coverage(instances, listings: dict[str, list[str]]) -> dict:
    """What the one-tree-per-repo approximation costs, as a number.

    An instance whose gold file is absent from its repo listing can never be retrieved
    by anything. Phase 2 keeps those instances in the denominator and scores them as
    misses, so this figure is the ceiling every retriever is measured against.
    """
    per_repo: dict[str, list[int]] = {}
    missing = []
    unlistable = []
    for inst in instances:
        listing = listings.get(inst.repo)
        if listing is None:
            # Counted, not skipped. The rate below is over the instances whose repo
            # could be listed, and the set that could not is exactly the repositories
            # that failed to list - which is not a random sample of them.
            unlistable.append(inst.instance_id)
            continue
        present = inst.gold_files[0] in set(listing)
        per_repo.setdefault(inst.repo, []).append(int(present))
        if not present:
            missing.append((inst.instance_id, inst.gold_files[0]))
    covered = sum(sum(v) for v in per_repo.values())
    total = sum(len(v) for v in per_repo.values())
    return {
        "covered": covered,
        "total": total,
        # None, not 0.0. A coverage of zero and a coverage nobody could measure are
        # different claims and read identically as a number - the same rule
        # `apps/_platform/cache.py` states for an unasked cache.
        "rate": covered / total if total else None,
        "per_repo": {r: (sum(v), len(v)) for r, v in per_repo.items()},
        "missing": missing,
        "unlistable": unlistable,
    }
