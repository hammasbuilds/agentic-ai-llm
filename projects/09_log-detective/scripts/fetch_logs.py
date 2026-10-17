r"""Fetch the Loghub corpus: real production logs from nine different systems.

    python scripts/fetch_logs.py              # -> D:\loghub-data\logs (or --work)
    python scripts/fetch_logs.py --list       # what it would fetch, and how big

The logs committed under `data/` are this repository's own - 1,005 lines of pytest and
git output. They are real, and they are nowhere near enough to say anything about log
mining: 973 scored lines collapse to 224 templates, a compression of 4.3x, which is a
statement about the sample rather than about the miner. Over 25,567 lines of one real
syslog the same code reports 73.5x.

So the numbers this project quotes are measured over Loghub, the standard corpus for log
parsing research (logpai/loghub, archived on Zenodo). Nine systems rather than one,
because a template miner tuned on syslog and never shown a Hadoop job log has been tuned
to one log format.

The data is NOT committed. It is 250 MB of other people's logs under their own terms, and
this script is the reproducible way to get exactly what was measured.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ZENODO = "https://zenodo.org/records/8196385/files/{archive}?download=1"

#: system -> (archive, the log file inside it, lines as Loghub documents them).
#: Chosen for variety and for staying under a few hundred MB: distributed systems, a
#: supercomputer, an operating system, a web server, a mobile app and a desktop tool.
DATASETS = {
    "linux": ("Linux.tar.gz", "Linux.log", 25_567),
    "apache": ("Apache.tar.gz", "Apache.log", 56_481),
    "zookeeper": ("Zookeeper.tar.gz", "Zookeeper.log", 74_380),
    "proxifier": ("Proxifier.tar.gz", "Proxifier.log", 21_329),
    # Loghub's directory calls this one OpenSSH and its download link says SSH.tar.gz;
    # the Zenodo record 404s on the directory's name.
    "openssh": ("SSH.tar.gz", "SSH.log", 655_146),
    "healthapp": ("HealthApp.tar.gz", "HealthApp.log", 253_395),
    "hpc": ("HPC.zip", "HPC.log", 433_489),
    "hadoop": ("Hadoop.zip", None, 394_308),
    "openstack": ("OpenStack.tar.gz", None, 207_820),
}
AGENT = {"User-Agent": "Mozilla/5.0 (log-mining corpus fetch for a template miner)"}


def get(url: str, into: Path, tries: int = 3) -> bool:
    """Download to `into`, or report failure. One dataset must not stop the rest."""
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=AGENT)
            with urllib.request.urlopen(request, timeout=300) as answer, into.open("wb") as out:
                shutil.copyfileobj(answer, out)
            return True
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            if attempt == tries - 1:
                print(f"    gave up: {type(err).__name__}")
                return False
            time.sleep(3 + 5 * attempt)
    return False


def unpack(archive: Path, into: Path) -> list[Path]:
    """Extract, refusing any member that would land outside `into`.

    An archive is untrusted input: a member named `../../x` writes outside the directory
    it was extracted to, and `tarfile` obliged until Python 3.12 made that a choice.
    """
    into.mkdir(parents=True, exist_ok=True)
    before = set(into.rglob("*"))
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                target = (into / member).resolve()
                if not str(target).startswith(str(into.resolve())):
                    raise SystemExit(f"{archive.name}: member {member!r} escapes the directory")
            bundle.extractall(into)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(into, filter="data")
    return sorted(set(into.rglob("*")) - before)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work",
        default=r"D:\loghub-data" if sys.platform == "win32" else "/tmp/loghub-data",
        help="where the corpus lives; outside the repository",
    )
    parser.add_argument("--list", action="store_true", help="print the datasets and exit")
    parser.add_argument("--only", nargs="*", help="fetch only these systems")
    args = parser.parse_args(argv)

    if args.list:
        total = sum(lines for _, _, lines in DATASETS.values())
        for system, (archive, _, lines) in sorted(DATASETS.items()):
            print(f"  {system:<12} {lines:>10,} lines  {archive}")
        print(f"\n  {len(DATASETS)} systems, {total:,} lines")
        return 0

    work = Path(args.work)
    archives, logs = work / "archive", work / "logs"
    for folder in (archives, logs):
        folder.mkdir(parents=True, exist_ok=True)

    wanted = args.only or sorted(DATASETS)
    for system in wanted:
        if system not in DATASETS:
            print(f"  {system}: not a dataset; --list shows them")
            continue
        archive, member, _ = DATASETS[system]
        bundle = archives / archive
        destination = logs / system

        if destination.is_dir() and any(destination.iterdir()):
            print(f"  {system:<12} already unpacked")
            continue
        if not (bundle.is_file() and bundle.stat().st_size > 1000):
            print(f"  {system:<12} downloading {archive}", flush=True)
            if not get(ZENODO.format(archive=archive), bundle):
                continue
        written = unpack(bundle, destination)
        lines = 0
        for path in written:
            if path.is_file() and path.suffix in ("", ".log"):
                with path.open("rb") as handle:
                    lines += sum(1 for _ in handle)
        print(f"  {system:<12} {lines:>10,} lines in {len(written)} file(s)", flush=True)

    print(f"\n  corpus at {logs}")
    print("  measure it: python -m detective.cli templates <that path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
