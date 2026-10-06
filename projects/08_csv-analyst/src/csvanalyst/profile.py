"""Profile a CSV before anyone computes anything from it.

The failure this module exists for: a column that is 99.7% numbers and 0.3%
the string "N/A" is not a numeric column, and every tool that quietly coerces
it produces a mean over an unstated subset. The mean is then reported to four
decimal places, which makes it look considered.

So every column is classified with the *evidence* for the classification -
how many values parsed, how many did not, and which ones - and any column that
is nearly-but-not-quite numeric is flagged rather than coerced.

Standard library only: `csv` reads, `statistics` summarises.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# Strings that conventionally mean "missing" and are not data.
NULL_TOKENS = frozenset(
    {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "unknown", "missing"}
)

# Numeric sentinels that are not measurements. Averaging them is the classic
# silent corruption: -999 in a temperature column drags the mean down by years.
SENTINELS = (-999, -9999, -99, -1, 999, 9999)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
)

_NUMERIC_RE = re.compile(r"^-?[\d,]*\.?\d+([eE][-+]?\d+)?$")


def _is_null(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def parse_number(value: str) -> float | None:
    """Parse a number, tolerating thousands separators and surrounding space.

    A value that overflows to infinity is not a number this returns. `float("1e400")`
    is `inf`, and `1e400` matches the numeric pattern, so a single cell holding it
    used to become infinity and travel the length of the tool:

      * `honest_mean(["1e400", "1", "2"])` returned `(inf, 3, 0)` - a mean of
        infinity, reported as computed over all three values with none skipped;
      * `histogram` raised `ValueError: cannot convert float NaN to integer`, because
        `inf - inf` is NaN;
      * `sparkline` drew a polyline whose other points had all collapsed to one
        coordinate, with no error at all.

    `inf` is an artefact of a 64-bit float, not something a CSV says. Returning None
    puts the cell in the unparseable count this tool already reports, which is the
    honest place for a value it could not use. Keeping it was the alternative, and
    three different parts of the tool each did something different with it.
    """
    v = value.strip().replace(",", "")
    if not v or not _NUMERIC_RE.match(value.strip()):
        return None
    try:
        parsed = float(v)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_date(value: str, formats: tuple[str, ...] = _DATE_FORMATS) -> date | None:
    v = value.strip()
    if len(v) < 6 or not any(sep in v for sep in "-/"):
        return None  # cheap reject before the expensive format loop
    for fmt in formats:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def detect_date_format(values: list[str], sample: int = 200) -> str | None:
    """Find the one format a column uses, from a sample.

    Trying all eleven formats against every value costs eleven exceptions per
    row. On a 500,000-row file that dominated the entire profile run. A column
    uses one format, so establish it from a sample and then parse with that
    format alone.
    """
    counts: Counter = Counter()
    for v in values[:sample]:
        stripped = v.strip()
        if len(stripped) < 6:
            continue
        for fmt in _DATE_FORMATS:
            try:
                datetime.strptime(stripped, fmt)
            except ValueError:
                continue
            counts[fmt] += 1
            break
    if not counts:
        return None
    best, hits = counts.most_common(1)[0]
    considered = min(len(values), sample)
    return best if considered and hits / considered >= 0.5 else None


@dataclass
class ColumnProfile:
    name: str
    index: int
    total: int
    nulls: int
    kind: str  # "numeric" | "date" | "categorical" | "text" | "empty"
    parsed: int = 0  # values that parsed as the chosen kind
    unparsed_examples: list[str] = field(default_factory=list)
    unique: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    top_values: list[tuple[str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def null_rate(self) -> float:
        return self.nulls / self.total if self.total else 0.0

    @property
    def present(self) -> int:
        return self.total - self.nulls

    @property
    def parse_rate(self) -> float:
        """Share of non-null values that parsed as the declared kind."""
        return self.parsed / self.present if self.present else 0.0

    is_identifier: bool = False

    @property
    def is_quantity(self) -> bool:
        """A numeric column it is meaningful to average.

        Excludes identifiers and contaminated columns, so nothing downstream
        can report a statistic the profile has already warned about - the
        first version printed `mean CustomerID = 15,316` immediately below a
        warning saying that number was meaningless.
        """
        return self.kind == "numeric" and not self.is_identifier and not self.is_contaminated

    @property
    def is_contaminated(self) -> bool:
        """Mostly numeric, not entirely. The dangerous case.

        A fully-text column is obvious. A column that is 99.7% numbers gets
        treated as numeric by every convenient tool, and the 0.3% vanishes
        from the denominator without appearing anywhere in the output.
        """
        return self.kind == "numeric" and 0.0 < (1 - self.parse_rate) <= 0.25


@dataclass
class TableProfile:
    path: str
    rows: int
    columns: list[ColumnProfile]
    duplicate_rows: int
    ragged_rows: int
    delimiter: str
    encoding: str

    @property
    def contaminated(self) -> list[ColumnProfile]:
        return [c for c in self.columns if c.is_contaminated]

    @property
    def all_warnings(self) -> list[tuple[str, str]]:
        return [(c.name, w) for c in self.columns for w in c.warnings]


def _sniff(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


class NotDelimitedTextError(ValueError):
    """The file is not text with delimiters in it, so there is nothing to profile.

    The latin-1 fallback below decodes any byte sequence whatsoever, which is what it
    is for - but it also means a PNG decodes cleanly and goes on to be profiled. An
    independent review pointed `report` at one and got "2 rows and 1 columns (1 text),
    delimiter ',', read as latin-1", under a footer reading "Every figure above was
    computed by a query that ran and passed validation. No number here was written by
    a language model." Both sentences were true and the file was an image.

    A NUL byte is the discriminator. No delimited text file contains one, every common
    binary format does, and the alternative was worse in both directions: with a NUL in
    a header this crashed with `sqlite3.ProgrammingError: the query contains a null
    character` out of `CREATE TABLE`, a traceback from the storage layer for something
    the reader should have refused.
    """


#: How much of the file to look at before deciding it is not text. A NUL in a header
#: is in the first few bytes; one further in belongs to a binary payload, and reading
#: the whole of a large file to find it is not worth the time.
BINARY_SNIFF = 65_536


def _read(path: Path, limit: int | None) -> tuple[list[str], list[list[str]], str, str]:
    """Read a CSV, trying utf-8 then falling back.

    Real files are not always utf-8. Failing on a byte in row 40,000 after a
    minute of work is worse than decoding it approximately and saying so.

    What that tolerance must not extend to is a file that is not text at all - see
    `NotDelimitedTextError`.
    """
    with path.open("rb") as handle:
        head = handle.read(BINARY_SNIFF)
    if b"\x00" in head:
        where = "in its header" if b"\x00" in head.split(b"\n", 1)[0] else "in its contents"
        raise NotDelimitedTextError(
            f"{path.name} holds a NUL byte {where}, so it is not delimited text. "
            "No CSV contains one; most binary formats do."
        )

    encoding = "utf-8"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        encoding = "latin-1"
        text = path.read_text(encoding="latin-1")

    delimiter = _sniff(text[:8192])
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return [], [], delimiter, encoding

    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if limit is not None and i >= limit:
            break
        rows.append(row)
    return header, rows, delimiter, encoding


def _classify(name: str, index: int, values: list[str]) -> ColumnProfile:
    total = len(values)
    present = [v for v in values if not _is_null(v)]
    nulls = total - len(present)

    profile = ColumnProfile(
        name=name or f"column_{index}",
        index=index,
        total=total,
        nulls=nulls,
        kind="empty",
        unique=len(set(present)),
    )
    if not present:
        profile.warnings.append("every value is null or empty")
        return profile

    numbers = [parse_number(v) for v in present]
    numeric_ok = [n for n in numbers if n is not None]
    numeric_rate = len(numeric_ok) / len(present)

    # Only look for dates if the column is not already clearly numeric, and
    # only with the single format the column actually uses.
    date_fmt = None if numeric_rate >= 0.75 else detect_date_format(present)
    if date_fmt is None:
        dates_ok = []
    else:
        dates_ok = [d for d in (parse_date(v, (date_fmt,)) for v in present) if d is not None]
    date_rate = len(dates_ok) / len(present)

    if numeric_rate >= 0.75:
        profile.kind = "numeric"
        profile.parsed = len(numeric_ok)
        bad = [v for v, n in zip(present, numbers, strict=False) if n is None]
        profile.unparsed_examples = list(dict.fromkeys(bad))[:5]
        if numeric_ok:
            profile.minimum = min(numeric_ok)
            profile.maximum = max(numeric_ok)
            profile.mean = statistics.fmean(numeric_ok)
            profile.median = statistics.median(numeric_ok)
        _numeric_warnings(profile, numeric_ok)
    elif date_rate >= 0.75:
        profile.kind = "date"
        profile.parsed = len(dates_ok)
        fmts = (date_fmt,) if date_fmt else _DATE_FORMATS
        bad = [v for v in present if parse_date(v, fmts) is None]
        profile.unparsed_examples = list(dict.fromkeys(bad))[:5]
    else:
        ratio = profile.unique / len(present)
        profile.kind = "categorical" if ratio < 0.5 else "text"
        profile.parsed = len(present)
        profile.top_values = Counter(present).most_common(5)
        if profile.kind == "categorical" and profile.unique == 1:
            profile.warnings.append(
                f"constant: every row is {present[0]!r} - carries no information"
            )

    if profile.null_rate > 0.5:
        profile.warnings.append(f"{profile.null_rate:.0%} of values are missing")
    if profile.is_contaminated:
        profile.warnings.append(
            f"{len(present) - profile.parsed} of {len(present)} values are not numbers "
            f"({', '.join(repr(x) for x in profile.unparsed_examples[:3])}) - "
            f"any mean here silently excludes them"
        )
    return profile


def _numeric_warnings(profile: ColumnProfile, values: list[float]) -> None:
    if not values:
        return
    counts = Counter(values)
    # A negative sentinel is only a sentinel if it stands alone. In a column of
    # order quantities, -1 means "one item returned" and the column is full of
    # other negatives; flagging it there was a false positive on the UCI retail
    # data. Require the candidate to be the sole negative value present.
    negatives = {v for v in values if v < 0}
    for sentinel in SENTINELS:
        hits = counts.get(float(sentinel), 0)
        if not hits or hits / len(values) <= 0.01:
            continue
        if sentinel < 0 and negatives != {float(sentinel)}:
            continue
        profile.warnings.append(
            f"{hits} values equal {sentinel} ({hits / len(values):.0%}) - "
            f"likely a missing-value sentinel, not a measurement"
        )
    if len(values) > 2:
        try:
            spread = statistics.pstdev(values)
        except statistics.StatisticsError:
            spread = 0.0
        if spread == 0:
            profile.warnings.append("zero variance - every value is identical")
        elif profile.mean is not None and spread > 0:
            extreme = [v for v in values if abs(v - profile.mean) > 8 * spread]
            if extreme:
                profile.warnings.append(
                    f"{len(extreme)} value(s) beyond 8 standard deviations "
                    f"(e.g. {max(extreme, key=abs):g})"
                )
    if all(float(v).is_integer() for v in values[:200]) and profile.unique <= 12:
        profile.warnings.append(
            f"only {profile.unique} distinct integers - probably a code, not a quantity; "
            f"averaging it is meaningless"
        )

    if _looks_like_identifier(profile, values):
        profile.is_identifier = True
        profile.warnings.append(
            "looks like an identifier rather than a measurement - "
            f"its mean ({profile.mean:,.1f}) is not a meaningful quantity"
        )


_ID_WORDS = frozenset({"id", "ids", "no", "num", "code", "key", "ref", "number"})
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _name_tokens(name: str) -> list[str]:
    """Split a column name into words, honouring camelCase.

    `CustomerID` must tokenise to ['customer', 'id']. A regex looking for a
    non-letter before `id` missed it entirely, which is why the mean of
    CustomerID was reported as a quantity in the first run.
    """
    spaced = _CAMEL.sub(" ", name).replace("_", " ").replace("-", " ").replace(".", " ")
    return [t.lower() for t in spaced.split() if t]


def _looks_like_identifier(profile: ColumnProfile, values: list[float]) -> bool:
    """A numeric column that labels rows rather than measuring them.

    Caught because this tool computed `mean CustomerID = 15,316.247` on the UCI
    retail data and reported it beside genuine quantities as though it meant
    something. Two signals: the name says identifier, or the values are
    integers that are almost all distinct.
    """
    if not values or profile.mean is None:
        return False
    if not all(float(v).is_integer() for v in values[:200]):
        return False
    tokens = _name_tokens(profile.name)
    if tokens and tokens[-1] in _ID_WORDS:
        return True

    # Near-uniqueness alone is far too weak: [1, 2, 3, 4] is 100% unique and is
    # not an identifier, and a quantity running 0..59 is not either. Both were
    # wrongly flagged by the first version. Require enough rows to mean
    # anything, and values large enough that they are keys rather than counts.
    if len(values) < 50:
        return False
    nearly_unique = profile.unique / len(values) > 0.9
    large_magnitude = profile.minimum is not None and profile.minimum >= 1000
    return nearly_unique and large_magnitude


def profile_csv(path: Path, limit: int | None = None) -> TableProfile:
    """Profile one CSV file."""
    header, rows, delimiter, encoding = _read(Path(path), limit)
    width = len(header)

    ragged = sum(1 for r in rows if len(r) != width)
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    for r in rows:
        key = tuple(r)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)

    columns = []
    for i, name in enumerate(header):
        values = [r[i] if i < len(r) else "" for r in rows]
        columns.append(_classify(name.strip(), i, values))

    return TableProfile(
        path=str(path),
        rows=len(rows),
        columns=columns,
        duplicate_rows=duplicates,
        ragged_rows=ragged,
        delimiter=delimiter,
        encoding=encoding,
    )


def naive_mean(values: list[str]) -> float | None:
    """What a convenient tool computes: coerce, drop failures, average silently.

    Kept here to make the comparison in the README reproducible rather than
    asserted.
    """
    numbers = [parse_number(v) for v in values if not _is_null(v)]
    ok = [n for n in numbers if n is not None]
    if not ok:
        return None
    return statistics.fmean(ok)


def honest_mean(values: list[str]) -> tuple[float | None, int, int]:
    """(mean, used, excluded) - the same number, with its denominator stated."""
    present = [v for v in values if not _is_null(v)]
    numbers = [parse_number(v) for v in present]
    ok = [n for n in numbers if n is not None]
    if not ok:
        return None, 0, len(present)
    return statistics.fmean(ok), len(ok), len(present) - len(ok)


def is_finite(value: float | None) -> bool:
    """A value that can be arithmetic on.

    This had no caller anywhere in the repository, and the thing it checks for was
    reaching three places that each mishandled it - see `parse_number`. It is used
    now: `charts` filters with it before taking a minimum, where it used to filter
    after, so one non-finite value set the whole scale to NaN and the filter only
    removed that one point from the line.
    """
    return value is not None and math.isfinite(value)
