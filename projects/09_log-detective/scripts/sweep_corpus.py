r"""Is the compression cliff a fact about log mining, or about one machine's logs?

    python scripts/sweep_corpus.py                    # over D:\loghub-data\logs
    python scripts/sweep_corpus.py --lines 10000 --budget 60

`cost` prints the threshold sweep for one set of files. This runs it per system over the
nine Loghub systems and puts the results side by side, because a cliff measured on 973
lines of one machine's pytest output is a property of that sample until it is shown
somewhere else.

Each cell is run under a time budget, and a cell that runs out says so rather than
hanging. That is not a convenience: clustering compares every line against every
template in its token-count bucket, so the cost is quadratic in the number of templates,
and a tight threshold on a log of mostly-distinct messages produces thousands. 25,000
lines of the HPC log take 1.5 seconds at 0.6, 2.6 at 0.7, 60 at 0.8, and at 0.9 did not
finish in ten minutes. A sweep that stops talking is indistinguishable from one that
crashed, and the shape of the table is the finding here.
"""

from __future__ import annotations

import argparse
import multiprocessing
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

THRESHOLDS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)


def _one(lines: list[str], threshold: float, out) -> None:
    from detective.templates import extract

    result = extract(lines, threshold)
    out.send((len(result.templates), result.compression, result.distinct_messages_lost))


def extract_within(lines: list[str], threshold: float, budget: float):
    """`(templates, compression, lost)`, or None if it ran past `budget` seconds.

    In a process rather than a thread, because the work is a tight Python loop that
    never yields and cannot be interrupted from outside.
    """
    here, there = multiprocessing.Pipe(duplex=False)
    worker = multiprocessing.Process(target=_one, args=(lines, threshold, there), daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
        return None
    return here.recv() if here.poll() else None


def lines_of(folder: Path, cap: int) -> list[str]:
    """Every log line under `folder`, to `cap`.

    A ratio over the first 25,000 lines of a log is not the ratio over all of it, so the
    cap is printed with the table rather than left out of it.
    """
    out: list[str] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix not in ("", ".log"):
            continue
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                out.append(raw.rstrip("\n"))
                if len(out) >= cap:
                    return out
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work", default=r"D:\loghub-data" if sys.platform == "win32" else "/tmp/loghub-data"
    )
    parser.add_argument("--lines", type=int, default=25_000, help="per system")
    parser.add_argument("--budget", type=float, default=90.0, help="seconds per cell")
    args = parser.parse_args(argv)

    logs = Path(args.work) / "logs"
    systems = sorted(p for p in logs.iterdir() if p.is_dir()) if logs.is_dir() else []
    if not systems:
        print(f"  no corpus under {logs}")
        print("  fetch it: python scripts/fetch_logs.py")
        return 1

    print(f"\n  Loghub, {len(systems)} systems, first {args.lines:,} lines of each at most.")
    print("  'lost' is the share of distinct messages with no template of their own.")
    print(f"  '--' is a cell that ran past {args.budget:.0f}s and was stopped.\n")
    header = f"  {'system':<11} {'scored':>7} " + "".join(f"{t:>9}" for t in THRESHOLDS)
    print(header)
    print("  " + "-" * (len(header) - 2))

    losses: dict[float, list[float]] = {}
    timeouts = 0
    for folder in systems:
        lines = lines_of(folder, args.lines)
        scored = sum(1 for raw in lines if raw.strip())
        if scored < 100:
            print(f"  {folder.name:<11} {scored:>7}  too few lines to sweep")
            continue
        ratios = f"  {folder.name:<11} {scored:>7} "
        lost = f"  {'':<11} {'lost':>7} "
        for threshold in THRESHOLDS:
            got = extract_within(lines, threshold, args.budget)
            if got is None:
                timeouts += 1
                ratios += f"{'--':>9}"
                lost += f"{'--':>9}"
                continue
            _, compression, messages_lost = got
            ratios += f"{compression:>8.1f}x"
            share = messages_lost / scored
            lost += f"{share:>8.0%} "
            losses.setdefault(threshold, []).append(share)
        print(ratios)
        print(lost + "\n")

    if losses:
        print("  median share of distinct messages lost, across systems")
        for threshold, shares in sorted(losses.items(), reverse=True):
            print(f"    {threshold:>4} {statistics.median(shares):>7.0%}")
    if timeouts:
        print(f"\n  {timeouts} cell(s) stopped at {args.budget:.0f}s. Clustering is")
        print("  quadratic in the number of templates, and a tight threshold on a log of")
        print("  mostly-distinct messages produces thousands of them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
