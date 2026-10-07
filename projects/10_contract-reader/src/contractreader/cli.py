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


#: Byte-order marks, longest first so UTF-32 is not read as UTF-16. A UTF-16 export
#: is text that is full of NUL bytes, and the refusal below used to turn one away with
#: the words "No licence contains one" - which a licence saved by a Windows editor
#: falsifies. A mark is a statement about the encoding, so the honest rule is: decode
#: what declares itself, refuse what has NULs and no mark.
BOM_ENCODINGS = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


def declared_encoding(head: bytes) -> str | None:
    """The encoding a byte-order mark declares, or None if there is no mark.

    The codec is the BARE `utf-16` / `utf-32`, not `utf-16-le`. Python consumes the
    mark only for the bare names and for `utf-8-sig`; with an explicit-endian codec
    the `\ufeff` is decoded as the first CHARACTER of the file. This mapped the
    little-endian mark to `utf-16-le`, so an Excel "Unicode Text" export was accepted
    - the refusal was fixed - and then read with an invisible character glued to the
    front of its first field. Three tools, three different wrong answers on data whose
    UTF-8 twin was right: a column named `\ufeffqty` that crashed a Windows console,
    a log line whose date no longer matched the date pattern so the templates and the
    compression figure both moved, and a citation span off by one.

    The bare names infer the endianness from the mark, which is what the mark is for.
    `_strip_mark` is belt and braces for a file whose mark survives anyway.
    """
    for mark, encoding in BOM_ENCODINGS:
        if head.startswith(mark):
            return encoding
    return None


def _strip_mark(text: str) -> str:
    """Any leftover byte-order mark, removed. Only ever the first character."""
    return text.removeprefix("\ufeff")


#: How much of a file to look at before deciding it is not text. A NUL in the first
#: block is what every common binary format has and no licence has.
BINARY_SNIFF = 65_536


def _not_a_licence(path: Path) -> str | None:
    """Why this file cannot be read as a licence, or None if it can be tried.

    An independent review pointed `read` at a `.csv` and got "family: unknown,
    1 clause(s)" with an empty obligations table and exit 0; a PNG gave the same, and
    an empty file gave "0 clause(s)". Every one of those is a report, and a tool whose
    whole promise is "cite the span behind every claim" answered about a file in which
    it had found nothing to cite.

    The empty obligations table is the part that misleads. A reader who passes the
    wrong path gets the same output as a reader whose licence genuinely imposes no
    obligations, and exit 0 says the run succeeded.
    """
    if not path.is_file():
        return f"not a file: {path}"
    try:
        with path.open("rb") as handle:
            head = handle.read(BINARY_SNIFF)
    except OSError as exc:
        return f"cannot read {path.name}: {exc.strerror or exc}"
    if not head:
        return f"{path.name} is empty: there is no licence text in it"
    if declared_encoding(head) is None and b"\x00" in head:
        return (
            f"{path.name} holds a NUL byte and no byte-order mark, so it is not text. "
            "A UTF-16 or UTF-32 licence declares itself with a mark; most binary "
            "formats do not."
        )
    return None


def _read_command(args: argparse.Namespace) -> int:
    path = Path(args.path)
    refusal = _not_a_licence(path)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    with path.open("rb") as handle:
        declared = declared_encoding(handle.read(4))
    reading = read(
        str(path), _strip_mark(path.read_text(encoding=declared or "utf-8", errors="replace"))
    )

    # A file this reader recognised nothing in is not a licence it read. Printing an
    # empty obligations table under "family: unknown" and exiting 0 made a `.csv`
    # indistinguishable from a permissive licence with nothing to flag.
    if reading.family == "unknown" and not reading.findings and not reading.rejected:
        print(
            f"{path.name}: no licence family and no obligation phrase found, so there "
            "is nothing here to cite. Pass --anyway to print the empty reading.",
            file=sys.stderr,
        )
        if not args.anyway:
            return 1

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
    # "no licence files found" is a claim about a directory, and it was made about
    # directories that are not there. The exit code was right and the sentence was
    # not: a typo and an empty folder are different answers, and only one of them is
    # about the folder the reader meant.
    if not root.exists():
        print(f"no such directory: {args.path}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"not a directory: {args.path}", file=sys.stderr)
        return 2
    readings = _read_all(root)
    if not readings:
        print(f"no licence files found under {root}", file=sys.stderr)
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
    r.add_argument(
        "--anyway",
        action="store_true",
        help="print the reading even when nothing was recognised in the file",
    )
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
