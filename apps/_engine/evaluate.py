"""Scoring for Phase 2: recall@k, cut by how discoverable the file was to begin with.

Phase 1 established that 51.3% of SWE-bench Lite issues never name the file to fix.
An aggregate recall number hides exactly that split - a retriever can look strong purely
by doing well on the half where the answer is written in the text. So every score here
is reported twice: overall, and per discoverability tier.

The tier breakdown is the result. If BM25 scores highly when the path is quoted and
collapses when it is not, then what a single SWE-bench number rewards is string matching,
and the reasoning half of the benchmark is being graded on a retrieval failure.

An instance whose gold file is missing from the repo listing is kept in the denominator
and scored as a miss. It cannot be retrieved by anything, so dropping it would flatter
every retriever equally and by an amount nobody could see.
"""

from __future__ import annotations

from collections import defaultdict

KS = (1, 3, 5, 10, 20)


def recall_at_k(ranked: list[str], gold: str, k: int) -> int:
    return int(gold in ranked[:k])


def resolve(generated: list[str], listing: set[str]) -> list[str]:
    """Map generated paths onto real repository paths where the prefix differs.

    A generative retriever names a module, not a repository path, and the two are not
    always the same string. matplotlib's package lives under `lib/`, so the model
    answers `matplotlib/widgets.py` for a file whose path is `lib/matplotlib/widgets.py`.
    Scored literally, every correct matplotlib answer is a miss - which is what dragged
    that arm to 22.2% on one tier while scoring 96.1% on another.

    A generated path is resolved only when exactly one real file ends with it on a
    directory boundary. Ambiguous matches are left alone: picking one of several would
    hand the arm a free guess, which is the opposite of what this is for.
    """
    out: list[str] = []
    for p in generated:
        if p in listing:
            out.append(p)
            continue
        suffix = "/" + p
        hits = [f for f in listing if f.endswith(suffix)]
        out.append(hits[0] if len(hits) == 1 else p)
    return out


def summarize(results: list[dict], ks: tuple[int, ...] = KS) -> dict:
    """results: [{instance_id, repo, tier, gold, ranked, retriever}, ...]"""
    by_retriever: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_retriever[r["retriever"]].append(r)

    out: dict[str, dict] = {}
    for name, rows in by_retriever.items():
        overall = {
            f"recall@{k}": sum(recall_at_k(r["ranked"], r["gold"], k) for r in rows) / len(rows)
            for k in ks
        }

        by_tier: dict[str, dict] = {}
        tiers: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            tiers[r["tier"]].append(r)
        for tier, trows in tiers.items():
            by_tier[tier] = {
                "n": len(trows),
                # The numerator too, because the rate alone was printed to one decimal
                # on tiers as small as 18 instances - where one instance is 5.6
                # percentage points, so the digit after the point was noise shown with
                # the authority of a measurement. `hits@10` lets the table print the
                # fraction the rate came from.
                **{
                    f"hits@{k}": sum(1 for t in trows if recall_at_k(t["ranked"], t["gold"], k) > 0)
                    for k in ks
                },
                **{
                    f"recall@{k}": sum(recall_at_k(t["ranked"], t["gold"], k) for t in trows)
                    / len(trows)
                    for k in ks
                },
            }

        by_repo: dict[str, dict] = {}
        repos: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            repos[r["repo"]].append(r)
        for repo, rrows in repos.items():
            by_repo[repo] = {
                "n": len(rrows),
                "recall@10": sum(recall_at_k(r["ranked"], r["gold"], 10) for r in rrows)
                / len(rrows),
            }

        out[name] = {
            "n": len(rows),
            "overall": overall,
            "by_tier": by_tier,
            "by_repo": by_repo,
            "mean_returned": sum(len(r["ranked"]) for r in rows) / len(rows),
        }
    return out


def fabrication_rate(results: list[dict], listings: dict[str, list[str]]) -> dict:
    """For a generative retriever: how many named paths do not exist in the repo?

    A model that invents `django/db/models/fields/related.py` when the real file is
    `related_descriptors.py` has not retrieved anything - it has produced a plausible
    string. Recall alone cannot tell the two apart.
    """
    named = 0
    real = 0
    per_instance = []
    # An instance whose repo could not be listed is skipped, and saying nothing about
    # that reports a rate over a denominator nobody can see - while the skipped set is
    # exactly the repositories that failed to list, which is not a random sample.
    unlistable = 0
    for r in results:
        listing = set(listings.get(r["repo"], []))
        if not listing:
            unlistable += 1
            continue
        exists = [p for p in r["ranked"] if p in listing]
        named += len(r["ranked"])
        real += len(exists)
        per_instance.append(len(exists) / len(r["ranked"]) if r["ranked"] else 0.0)
    return {
        "paths_named": named,
        "paths_that_exist": real,
        "rate_exists": real / named if named else 0.0,
        "mean_per_instance": sum(per_instance) / len(per_instance) if per_instance else 0.0,
        "instances_scored": len(per_instance),
        "instances_unlistable": unlistable,
    }


def _bar(x: float, width: int = 28) -> str:
    return "#" * round(width * x)


def print_report(summary: dict, ks: tuple[int, ...] = KS) -> None:
    print("\n" + "=" * 74)
    print("RECALL@K - overall")
    print("=" * 74)
    header = "  retriever".ljust(22) + "".join(f"@{k}".rjust(9) for k in ks)
    print(header)
    print("  " + "-" * 70)
    for name, s in summary.items():
        row = f"  {name:20}"
        for k in ks:
            row += f"{s['overall'][f'recall@{k}']:8.1%} "
        print(row)

    print("\n" + "=" * 74)
    print("RECALL@10 - by how discoverable the gold file was (Phase 1 tiers)")
    print("=" * 74)
    order = ["full_path", "basename", "stem_only", "not_mentioned"]
    for name, s in summary.items():
        print(f"\n  {name}")
        for tier in order:
            t = s["by_tier"].get(tier)
            if not t:
                continue
            v, n = t["recall@10"], t["n"]
            # One decimal place is only meaningful when n supports it: each instance
            # moves the rate by 100/n points, so a tier of 18 is quoted whole and a
            # tier of 153 to one decimal. The fraction is printed either way, which is
            # the reading that does not need a rule.
            places = 1 if n >= 100 else 0
            rate = f"{v:6.{places}%}"
            print(f"    {tier:16} n={n:4}  {rate:>7}  {t['hits@10']:4}/{n:<4} {_bar(v)}")

    print("\n" + "=" * 74)
    print("RECALL@10 - by repository")
    print("=" * 74)
    repos = sorted(
        {r for s in summary.values() for r in s["by_repo"]},
        key=lambda r: -max(s["by_repo"].get(r, {}).get("n", 0) for s in summary.values()),
    )
    names = list(summary)
    print("  repo".ljust(30) + "n".rjust(5) + "".join(n[:10].rjust(12) for n in names))
    print("  " + "-" * 70)
    for repo in repos:
        n = max(summary[x]["by_repo"].get(repo, {}).get("n", 0) for x in names)
        row = f"  {repo:28}{n:5}"
        for name in names:
            v = summary[name]["by_repo"].get(repo, {}).get("recall@10")
            row += f"{v:11.1%} " if v is not None else " " * 12
        print(row)
