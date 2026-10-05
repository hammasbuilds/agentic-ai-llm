"""Command line for contract-reader. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .obligations import OBLIGATIONS, Reading, conflicts, read

LICENCE_NAMES = {
    "LICENSE",
    "LICENSE.TXT",
    "LICENSE.MD",
    "LICENCE",
    "LICENCE.TXT",
    "COPYING",
    "LICENSE.RST",
}
SKIP = {".venv", ".venvs", "node_modules", "__pycache__", ".git", ".tox"}


# A documentation page that POINTS AT a licence is not a licence. Sphinx and MkDocs
# projects ship `docs/license.rst` saying "see LICENSE in the project root", and reading
# those as licence files produced twelve unidentifiable "licences" and twelve conflict
# reports - a checker whose first duty is not to cry wolf.
DOC_DIRS = {"docs", "doc", "documentation", "source", "artwork"}


def _is_virtualenv(path: Path) -> bool:
    """A virtualenv, by its marker file rather than its name.

    SKIP listed `.venv` and `.venvs`, so `.venv-check` and `.venv-check2` were walked
    and the survey filled with third-party packages: 198 licence files where the
    README's measurement found 75. A name list cannot keep up with what people call
    their environments; `pyvenv.cfg` is what makes one.
    """
    return (path / "pyvenv.cfg").exists()


def _find(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    out = []
    for p in root.rglob("*"):
        if p.name.upper() not in LICENCE_NAMES:
            continue
        if any(x in p.parts for x in SKIP):
            continue
        if any(part.lower() in DOC_DIRS for part in p.parent.parts):
            continue
        if any(_is_virtualenv(parent) for parent in p.parents):
            continue
        out.append(p)
    return sorted(out)


def _read_all(root: Path) -> list[Reading]:
    readings = []
    for path in _find(root):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            shown = str(path.relative_to(root))
        except ValueError:
            shown = str(path)
        readings.append(read(shown, raw))
    return readings


def _read_command(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    reading = read(str(path), path.read_text(encoding="utf-8", errors="replace"))

    print(f"{reading.path}")
    print(f"  family: {reading.family}")
    if reading.family_citation:
        c = reading.family_citation
        print(f'    because chars {c.start}-{c.end} say "{c.phrase}"')
        print(f"    in clause: {c.clause}")
    print(f"  {len(reading.clauses)} clause(s)")
    print()
    print("  OBLIGATIONS  (each with the span that proves it)")
    for finding in sorted(reading.findings, key=lambda f: f.risk, reverse=True):
        c = finding.citation
        print(f"    [{finding.risk:6s}] {finding.obligation}")
        print(f"             {finding.description}")
        print(f'             chars {c.start}-{c.end} in {c.clause}: "{c.phrase}"')
        if args.verbose:
            print(f"             {c.sentence[:150]}")
    if reading.rejected:
        print()
        print("  REJECTED  (phrase found, context said it does not count)")
        for name, why in reading.rejected:
            print(f"    {name}: {why[:120]}")
    return 0


def _survey_command(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    readings = _read_all(root)
    if not readings:
        print("no licence files found", file=sys.stderr)
        return 2

    families = Counter(r.family for r in readings)
    rejected = sum(len(r.rejected) for r in readings)
    print(f"{len(readings)} licence file(s); {rejected} keyword match(es) rejected on context")
    print(f"  {dict(families)}")
    print()
    print("  NON-PERMISSIVE, with the clause that proves it")
    found = False
    for reading in readings:
        if reading.family in ("GPL", "AGPL-3.0", "MPL-2.0", "LGPL"):
            found = True
            c = reading.family_citation
            print(f"    {reading.family:9s} {reading.path}")
            if c:
                print(f'              chars {c.start}-{c.end}: "{c.phrase}"')
    if not found:
        print("    none")

    print()
    print(f"  CONFLICTS against a {args.project} project")
    any_conflict = False
    for reading in readings:
        why = conflicts(args.project, reading)
        if why:
            any_conflict = True
            print(f"    {reading.path}")
            print(f"        {why}")
    if not any_conflict:
        print("    none")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "licences": len(readings),
                    "families": dict(families),
                    "rejected_matches": rejected,
                    "files": [
                        {
                            "path": r.path,
                            "family": r.family,
                            "copyleft": r.copyleft,
                            "obligations": sorted(r.obligations),
                            "conflict": conflicts(args.project, r),
                        }
                        for r in readings
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


def _obligations_command(_: argparse.Namespace) -> int:
    print("Obligations this reads for, and the risk each carries:\n")
    for key, (description, risk, phrases) in OBLIGATIONS.items():
        print(f"  [{risk:6s}] {key}")
        print(f"           {description}")
        print(f"           matched by: {phrases[0]!r} and {len(phrases) - 1} more")
    print("\nEvery match is checked against the sentence around it before it")
    print("becomes a finding, and the span is reported so it can be disputed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="contract-reader",
        description="Read a licence, and cite the span behind every claim.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("read", help="read one licence file")
    r.add_argument("path")
    r.add_argument("--verbose", "-v", action="store_true")
    r.set_defaults(func=_read_command)

    s = sub.add_parser("survey", help="every licence under a folder")
    s.add_argument("path")
    s.add_argument("--project", default="MIT", help="the licence your project ships under")
    s.add_argument("--json")
    s.set_defaults(func=_survey_command)

    o = sub.add_parser("obligations", help="what it looks for")
    o.set_defaults(func=_obligations_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
