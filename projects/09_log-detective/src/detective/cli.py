"""Command line for log-detective. argparse only - the core has no dependencies."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .templates import extract, sweep

#: Byte-order marks, longest first so UTF-32 is not read as UTF-16. A UTF-16 export
#: is text that is full of NUL bytes, and the refusal below used to turn one away with
#: the words "No log file contains one" - which a log exported by a Windows tool
#: falsifies. A mark is a statement about the encoding, so the honest rule is: decode
#: what declares itself, refuse what has NULs and no mark.
BOM_ENCODINGS = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


def declared_encoding(head: bytes) -> str | None:
    """The encoding a byte-order mark declares, or None if there is no mark."""
    for mark, encoding in BOM_ENCODINGS:
        if head.startswith(mark):
            return encoding
    return None


#: How much of a file to look at before deciding it is not text. A NUL in the first
#: block is what every common binary format has and no log file has.
BINARY_SNIFF = 65_536


def _is_text(path: Path) -> bool:
    """Whether this is a log file rather than a binary one.

    `errors="replace"` below decodes any byte sequence at all, which is right for a log
    with one bad byte in it and wrong for a file that is not text. An independent
    review pointed `templates` at a PNG and got "4 lines -> 4 templates (1.0x) at
    threshold 0.6, 0 template(s) merged distinct messages; 0 distinction(s) lost" - a
    complete, confident report about an image, including a compression ratio.

    It also crashed on the way out, because the replacement characters it had just
    produced could not be encoded by the Windows console. That was the only reason
    anybody noticed.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(BINARY_SNIFF)
    except OSError:
        return False
    # A byte-order mark says the file is UTF-16 or UTF-32, which is text full of NUL
    # bytes. The check used to say "No log file contains one", which an exported log
    # from a Windows tool falsifies.
    return declared_encoding(head) is not None or b"\x00" not in head


def _read_lines(path: Path) -> list[str]:
    """One log's lines, decoded as it declares itself or as utf-8 with replacements."""
    with path.open("rb") as handle:
        declared = declared_encoding(handle.read(4))
    encoding = declared or "utf-8"
    return path.read_text(encoding=encoding, errors="replace").splitlines()


def _read(paths: list[str]) -> list[str]:
    """Every line of every named log.

    A binary file is named on stderr and left out rather than ending the run: these
    commands take a directory, and one stray file in it should not stop the other
    forty being read. What must not happen is leaving it out in silence - a corpus
    that quietly shrinks is the failure this tool exists to measure.
    """
    lines: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(path.glob("*.log"))
            if not found:
                print(f"no .log files in {path}", file=sys.stderr)
            for f in found:
                if not _is_text(f):
                    print(f"not a text log, skipped: {f.name}", file=sys.stderr)
                    continue
                lines += _read_lines(f)
        elif path.is_file():
            if not _is_text(path):
                print(
                    f"{path.name} holds a NUL byte and no byte-order mark, so it is "
                    "not a text log. A UTF-16 or UTF-32 log declares itself with a "
                    "mark; most binary formats do not.",
                    file=sys.stderr,
                )
                continue
            lines += _read_lines(path)
        else:
            print(f"no such path: {path}", file=sys.stderr)
    return lines


def _nothing_read(paths: list[str]) -> int:
    """Exit 2, and say which of the several reasons it was.

    This used to be a bare `return 2`: an empty file, a directory with no logs in it
    and a path that does not exist all produced no output whatsoever and the same
    status. A reader cannot tell a typo from an empty log, and the one thing a tool
    built to report what extraction destroyed must not do is say nothing at all.
    """
    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.stat().st_size == 0:
            print(f"{path.name} is empty: no lines to extract templates from", file=sys.stderr)
            return 2
    print("no log lines were read from: " + ", ".join(paths), file=sys.stderr)
    return 2


def _templates_command(args: argparse.Namespace) -> int:
    lines = _read(args.paths)
    if not lines:
        return _nothing_read(args.paths)
    result = extract(lines, threshold=args.threshold)

    # The blank count is named here too, so this command and `cost` describe the same
    # corpus. They used to differ by 32 lines on the same input, with the compression
    # ratio computed over one number and printed under the other.
    blank = f", {result.blank_lines:,} blank and not scored" if result.blank_lines else ""
    print(
        f"{result.lines:,} lines -> {len(result.templates)} templates "
        f"({result.compression:.1f}x) at threshold {result.threshold}{blank}"
    )
    print(
        f"  {len(result.merged_templates)} template(s) merged distinct messages; "
        f"{result.distinct_messages_lost} distinction(s) lost"
    )
    print()
    for template in result.templates[: args.limit]:
        flag = " MERGED" if template.merged else ""
        print(f"  {template.count:6d}x{flag}  {template.text[:96]}")
        if template.merged and args.verbose:
            for example in template.examples(3):
                print(f"            was: {example[:88]}")
    return 0


def _cost_command(args: argparse.Namespace) -> int:
    """Compression against what it destroys. The point of the tool."""
    lines = _read(args.paths)
    if not lines:
        return _nothing_read(args.paths)
    # Both numbers, because this header printed the lines READ while every ratio in
    # the table below divides by the lines SCORED. One input gave two corpus sizes -
    # 1,005 under this header and 973 in `templates` - and the README and the badge
    # both took the larger.
    blanks = sum(1 for raw in lines if not raw.strip())
    if blanks:
        print(
            f"{len(lines):,} lines read, {len(lines) - blanks:,} scored "
            f"({blanks:,} blank); every ratio below is over the scored count\n"
        )
    else:
        print(f"{len(lines):,} lines, none blank\n")
    print(
        f"{'thresh':>7s} {'templates':>10s} {'compression':>12s} "
        f"{'merged':>7s} {'distinct lost':>14s} {'singletons':>11s}"
    )
    rows = sweep(lines)
    for result in rows:
        print(
            f"{result.threshold:7.1f} {len(result.templates):10d} "
            f"{result.compression:11.1f}x {len(result.merged_templates):7d} "
            f"{result.distinct_messages_lost:14d} {len(result.singletons):11d}"
        )
    print()
    print("  'distinct lost' counts messages that no longer have a template of")
    print("  their own. Compression is bought by deciding two lines are the same.")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "threshold": r.threshold,
                        "templates": len(r.templates),
                        "compression": round(r.compression, 3),
                        "merged_templates": len(r.merged_templates),
                        "distinct_messages_lost": r.distinct_messages_lost,
                        "singletons": len(r.singletons),
                    }
                    for r in rows
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 0


def _rare_command(args: argparse.Namespace) -> int:
    """The lines that happened once. Usually the reason you opened the log."""
    lines = _read(args.paths)
    if not lines:
        return _nothing_read(args.paths)
    result = extract(lines, threshold=args.threshold)
    rare = result.rarest(args.limit)
    print(
        f"{len(result.singletons)} template(s) seen exactly once, of {len(result.templates)}\n"
    )
    for template in rare:
        print(f"  {template.count:4d}x  line {template.first_line:6d}  {template.text[:88]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="log-detective",
        description="Extract log templates, and report what the extraction destroyed.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("templates", help="extract templates at one threshold")
    t.add_argument("paths", nargs="+")
    t.add_argument("--threshold", type=float, default=0.6)
    t.add_argument("--limit", type=int, default=25)
    t.add_argument("--verbose", "-v", action="store_true")
    t.set_defaults(func=_templates_command)

    c = sub.add_parser("cost", help="compression against information destroyed")
    c.add_argument("paths", nargs="+")
    c.add_argument("--json")
    c.set_defaults(func=_cost_command)

    r = sub.add_parser("rare", help="templates seen once or twice")
    r.add_argument("paths", nargs="+")
    r.add_argument("--threshold", type=float, default=0.6)
    r.add_argument("--limit", type=int, default=15)
    r.set_defaults(func=_rare_command)

    return p


def _printable_stdout() -> None:
    """A log line can hold a character the console cannot encode, and printing one
    raised `UnicodeEncodeError: 'charmap' codec can't encode character` out of the
    middle of a report - after part of it had already been written. The report is
    about the log, so a character it cannot render is worth a replacement glyph, not
    a traceback."""
    for stream in (sys.stdout, sys.stderr):
        # Not a tty, or already closed: there is nothing to reconfigure and nothing
        # to report about it.
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _printable_stdout()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
