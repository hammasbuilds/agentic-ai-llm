"""Is this installed version actually vulnerable, and is this host in scope.

Two questions, both deterministic, and the first one is where every naive
scanner generates the noise that gets it muted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UPSTREAM = re.compile(r"^(\d+(?:\.\d+)*)")


class OutOfScopeError(PermissionError):
    """A target that was not authorised. NotAuthorisedError, not warned about."""


def in_scope(host: str, scope: set[str]) -> str:
    """Return the host, or refuse.

    Every collector calls this first. Scope is a set of exact host names on
    purpose: a wildcard is how an authorised scan becomes an unauthorised one.
    """
    if host not in scope:
        raise OutOfScopeError(f"{host} is not in the authorised scope")
    return host


def upstream(version: str) -> tuple[int, ...]:
    """The upstream part of a distribution version, as integers.

    ``1.10.0`` must sort above ``1.9.0``; a lexical comparison says otherwise,
    which is the first bug every version matcher ships.
    """
    match = _UPSTREAM.match(version.strip())
    if not match:
        raise ValueError(f"cannot read an upstream version from {version!r}")
    return tuple(int(p) for p in match.group(1).split("."))


def revision(version: str) -> str:
    """The distribution suffix — ``-4ubuntu1.2``. The backport signal."""
    match = _UPSTREAM.match(version.strip())
    return version.strip()[match.end() :] if match else ""


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    release: str = ""  # e.g. "jammy"


@dataclass(frozen=True)
class Advisory:
    cve: str
    package: str
    fixed_upstream: str
    # release -> the distribution version carrying the backported fix
    backported: dict = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Verdict:
    vulnerable: bool
    reason: str


UPSTREAM_BELOW_FIX = "upstream version is below the fix"
UPSTREAM_AT_OR_ABOVE = "upstream version is at or above the fix"
BACKPORTED = "distribution backported the fix without bumping upstream"
WRONG_PACKAGE = "advisory is for a different package"


def assess(package: Package, advisory: Advisory) -> Verdict:
    """The verdict a raw scanner gets wrong."""
    if package.name != advisory.package:
        return Verdict(False, WRONG_PACKAGE)
    if upstream(package.version) >= upstream(advisory.fixed_upstream):
        return Verdict(False, UPSTREAM_AT_OR_ABOVE)
    backports = advisory.backported or {}
    patched = backports.get(package.release)
    if patched and revision(package.version) >= revision(patched):
        return Verdict(False, BACKPORTED)
    return Verdict(True, UPSTREAM_BELOW_FIX)


def false_positive_rate(naive: list[Verdict], checked: list[Verdict]) -> float:
    """How much noise the backport table removed.

    ``naive`` is upstream comparison alone; ``checked`` consults the backports.
    The product's headline number.
    """
    if len(naive) != len(checked):
        raise ValueError("the two runs must cover the same findings")
    flagged = sum(1 for v in naive if v.vulnerable)
    if flagged == 0:
        return 0.0
    pairs = zip(naive, checked, strict=True)
    cleared = sum(1 for n, c in pairs if n.vulnerable and not c.vulnerable)
    return cleared / flagged
