"""Which documentation claims can be checked by running something.

Most doc linters assume every claim is checkable and produce a wall of
unfalsifiable findings, which is how they get turned off in week two.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

MECHANICAL = "mechanical"
JUDGEMENT = "judgement"

_PYTHON_VERSION = re.compile(r"python\s*(?:>=|≥)\s*(\d+\.\d+)", re.I)
_TEST_COUNT = re.compile(r"(\d[\d,]*)\s+tests\b", re.I)
_ZERO_DEPS = re.compile(r"\bzero\s+(?:runtime\s+)?dependencies\b", re.I)

# A backticked path, which either exists in the repository or does not.
_PATH = re.compile(r"`([\w./-]+\.(?:py|toml|md|json|yml|yaml|sh|cfg|txt))`")
# A count of things the repository either contains or does not.
#
# Spelled-out numbers are not a nicety. READMEs are written by people, and
# people write "Eleven standalone tools" and "All ten, at a glance" far more
# often than "11 tools". A checker that only reads digits found ZERO checkable
# claims in a real repository whose heading said "All ten" above a table of
# seven — which is the exact drift it exists to catch.
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}
_NOUNS = r"projects?|repos?|repositories|tools?|modules?|apps?|products?|labs?"
# The number must bind to the noun it precedes, with at most one adjective
# between them. A wider gap matched "3 seconds because project 01 has..." and
# reported it as a claim about project count — a number binds to the nearest
# noun, and letting it reach past one is how a checker invents findings.
_ADJECTIVE = r"(?:[a-z]+-[a-z]+|standalone|committed|finished|separate|distinct)\s+"
_COUNT = re.compile(
    rf"\b(\d[\d,]*|{'|'.join(_WORD_NUMBERS)})\s+(?:{_ADJECTIVE})?({_NOUNS})\b",
    re.I,
)
# A named dependency, which the project either declares or does not.
_DEPENDS = re.compile(r"\b(?:depends on|requires|built on)\s+`([\w.-]+)`", re.I)

_CHECKS = (
    ("python_version", _PYTHON_VERSION),
    ("test_count", _TEST_COUNT),
    ("zero_dependencies", _ZERO_DEPS),
    ("path_exists", _PATH),
    ("thing_count", _COUNT),
    ("depends_on", _DEPENDS),
)


@dataclass(frozen=True)
class Claim:
    text: str
    file: str = "README.md"
    line: int = 0

    @property
    def kind(self) -> str:
        return MECHANICAL if self.check is not None else JUDGEMENT

    @property
    def check(self) -> str | None:
        for name, pattern in _CHECKS:
            if pattern.search(self.text):
                return name
        return None


@dataclass(frozen=True)
class Verdict:
    claim: Claim
    checked: bool
    holds: bool | None
    detail: str


NOT_CHECKABLE = "unfalsifiable by running anything; a person decides"


#: A count that is not about the whole set. "One project per LangGraph shape",
#: "Two projects changed shape", "twelve per project", "added to three projects" -
#: each binds a number to the noun and none of them states how many the repository
#: has. Over 76 real checkouts these were 9 of the 30 claims reported false, every
#: one of them a bug in this checker rather than drift in a README.
#: The claim names a subdirectory, so it is about that directory and not about the
#: repository root whose pyproject.toml is the only fact available. "In `projects/`.
#: Zero runtime dependencies" is a statement about eleven packages, each of which
#: declares `dependencies = []`; the root declares thirteen for a web layer the
#: sentence never mentions.
_SCOPED_ELSEWHERE = re.compile(r"`[\w./-]+/`|\bin \[?`[\w./-]+/", re.IGNORECASE)

#: Nothing in here is ever a declared dependency.
_STDLIB = frozenset(sys.stdlib_module_names)

_NOT_A_TOTAL = re.compile(
    r"\b(?:per|each|apiece|of (?:the|its|them|these|those)|added to|changed|"
    r"were (?:designed|not|then)|some|both|either|across|only)\b",
    re.IGNORECASE,
)

#: A path named as something other than a file this repository contains: a
#: counterexample, another project's file, or one the reader creates. These were
#: most of the rest - `coverage.py` in "not `coverage.py`", Django's `runtests.py`,
#: a `robots.txt` on someone else's website, `claude_desktop_config.json` on the
#: reader's machine, `__MACOSX/._x.txt` inside a downloaded zip.
_NOT_OURS = re.compile(
    r"\b(?:not|rather than|instead of|unlike|without|no longer|never)\b\s+`|"
    r"\b(?:zip|archive|tarball|website|site|upstream|[Dd]jango|flask|numpy|pandas|"
    r"your|their|his|her|its own|someone else)\b",
    re.IGNORECASE,
)

#: The sentence says the file is produced, or lives outside the repository. Then its
#: absence is the documented state of affairs rather than a broken reference.
_GENERATED = re.compile(
    r"\b(?:gitignored|git-ignored|not committed|not tracked|untracked|generate[sd]?|"
    r"generating|writes?|wrote|written|produce[sd]?|emits?|prints?|printed|dumps?|"
    r"saves?|stores?|will (?:be )?(?:write|create)|"
    r"creates?|output|on your machine|your own)\b",
    re.IGNORECASE,
)


def _is_ignored(named: str, patterns: list[str]) -> bool:
    """Whether .gitignore covers this path. fnmatch, as git's own syntax mostly is."""
    import fnmatch  # noqa: PLC0415
    from pathlib import PurePosixPath  # noqa: PLC0415

    target = PurePosixPath(named)
    candidates = [named, target.name, *(str(p) for p in target.parents if str(p) != ".")]
    for pattern in patterns:
        bare = pattern.rstrip("/")
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, bare) or candidate == bare:
                return True
            # A directory pattern covers everything under it.
            if fnmatch.fnmatch(candidate, bare + "/*") or candidate.startswith(bare + "/"):
                return True
    return False


def verify(claim: Claim, facts: dict) -> Verdict:
    """Check a claim against facts collected from the repository.

    ``facts`` comes from running things — ``pyproject.toml``, a collected test
    count, the declared dependency list. Nothing here reasons about the claim.
    """
    check = claim.check
    if check is None:
        return Verdict(claim, False, None, NOT_CHECKABLE)

    if check == "python_version":
        stated = _PYTHON_VERSION.search(claim.text).group(1)
        actual = str(facts.get("requires_python", "")).lstrip(">=≥ ")
        return Verdict(
            claim,
            True,
            stated == actual,
            f"README says {stated}, project says {actual or 'nothing'}",
        )

    if check == "test_count":
        stated = int(_TEST_COUNT.search(claim.text).group(1).replace(",", ""))
        actual = facts.get("collected_tests")
        if actual is None:
            return Verdict(claim, False, None, "no collected test count available")
        return Verdict(
            claim,
            True,
            stated == actual,
            f"README says {stated}, pytest collected {actual}",
        )

    if check == "path_exists":
        root = facts.get("root")
        if root is None:
            return Verdict(claim, False, None, "no repository root to resolve against")
        from pathlib import Path  # noqa: PLC0415

        named = _PATH.search(claim.text).group(1)
        base = Path(root)
        found = (base / named).exists() or next(base.rglob(named), None) is not None
        if found:
            return Verdict(claim, True, True, f"{named} exists")

        # A missing file is only drift if the repository meant to have it. Over a
        # folder of 76 real checkouts this check reported 31 false claims and most
        # were neither false nor claims: a path the repository deliberately does not
        # track, a file the same sentence says will be generated, or a filename the
        # reader is told to create on their own machine. Declining is the honest
        # answer - it joins the "no fact to check against" bucket, which this
        # product already reports separately for exactly this reason.
        if _is_ignored(named, facts.get("ignored", [])):
            return Verdict(claim, False, None, f"{named} is under this repository's .gitignore")
        if _GENERATED.search(claim.text):
            return Verdict(
                claim, False, None, f"{named} is described as generated, not tracked"
            )
        if _NOT_OURS.search(claim.text):
            return Verdict(
                claim, False, None, f"{named} is not named as a file this repository holds"
            )
        return Verdict(claim, True, False, f"{named} is missing")

    if check == "thing_count":
        if _NOT_A_TOTAL.search(claim.text):
            return Verdict(claim, False, None, "a count of part of the set, not of the set")
        # A sentence can state several counts — "Eleven standalone tools, 11
        # projects in all" — and a fact may exist for only one of them.
        # Checking only the first match reports "no collected count of tools"
        # and silently drops a claim that was perfectly checkable.
        nouns = []
        for match in _COUNT.finditer(claim.text):
            raw = match.group(1).lower().replace(",", "")
            stated = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
            noun = match.group(2).lower().rstrip("s")
            nouns.append(noun)
            actual = facts.get(f"{noun}_count")
            if actual is not None:
                return Verdict(
                    claim, True, stated == actual, f"README says {stated}, found {actual}"
                )
        return Verdict(
            claim, False, None, f"no collected count of {'/'.join(dict.fromkeys(nouns))}"
        )

    if check == "depends_on":
        named = _DEPENDS.search(claim.text).group(1).lower()
        # A standard-library module is not a dependency, and a sentence naming one is
        # usually saying the opposite: "no runtime dependencies (the DOM is built on
        # `html.parser`)" was reported as a false claim that html.parser is declared.
        if named.split(".")[0] in _STDLIB:
            return Verdict(
                claim, False, None, f"{named} is in the standard library, not a dependency"
            )
        declared = [
            d.split("[")[0].split(">")[0].split("=")[0].strip().lower()
            for d in facts.get("dependencies", [])
        ]
        if not declared and "dependencies" not in facts:
            return Verdict(claim, False, None, "no declared dependency list")
        return Verdict(claim, True, named in declared, f"{named} in {declared or 'none'}")

    # zero_dependencies. The fact is the repository root's pyproject, so a claim
    # scoped to a subdirectory is not about it. "In `projects/`. Zero runtime
    # dependencies and zero LLM calls" was this checker's flagship finding - quoted
    # in its own README as real drift caught live - and it is true: all eleven
    # packages under that directory declare `dependencies = []`. The root declares
    # thirteen for the web layer, which the sentence never mentioned.
    sub = facts.get("sub_pyprojects", 0)
    if sub:
        return Verdict(
            claim,
            False,
            None,
            f"{sub} packages here declare their own dependencies, so a root-level "
            "claim cannot be settled from the root pyproject alone",
        )
    if _SCOPED_ELSEWHERE.search(claim.text):
        return Verdict(
            claim,
            False,
            None,
            "the claim is scoped to a subdirectory; the fact is the root pyproject",
        )
    actual = list(facts.get("dependencies", []))
    return Verdict(
        claim,
        True,
        not actual,
        f"README claims zero dependencies, project declares {actual or 'none'}",
    )


def verifiable_share(claims: list[Claim]) -> float:
    """Share of claims a machine can settle. The product's headline ratio."""
    if not claims:
        return 0.0
    return sum(1 for c in claims if c.kind == MECHANICAL) / len(claims)


def broken(verdicts: list[Verdict]) -> list[Verdict]:
    """Claims that were checked and do not hold. The pull request's contents."""
    return [v for v in verdicts if v.checked and v.holds is False]
