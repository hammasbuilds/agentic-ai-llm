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
    """Parse a number, tolerating thousands separators and surrounding space."""
    v = value.strip().replace(",", "")
    if not v or not _NUMERIC_RE.match(value.strip()):
        return None
    try:
        return float(v)
    except ValueError:
        return None


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


def _read(path: Path, limit: int | None) -> tuple[list[str], list[list[str]], str, str]:
    """Read a CSV, trying utf-8 then falling back.

    Real files are not always utf-8. Failing on a byte in row 40,000 after a
    minute of work is worse than decoding it approximately and saying so.
    """
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
    return value is not None and math.isfinite(value)
