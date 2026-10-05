"""Extract obligations and classify a licence, with every claim span-grounded.

Two rules, and the second is the one that matters:

1. A claim is produced only by a phrase that was found in the document.
2. **A phrase inside a negation or a compatibility clause does not count.**

Rule 2 exists because of a real false positive in this corpus. The Python
Software Foundation licence contains the exact string "GNU General Public
License" - in a sentence explaining that the PSF licence is *compatible* with
it. A keyword classifier reads `typing_extensions` as GPL, and a compliance
tool then raises an alarm about copyleft contamination that is not there.

So every match is checked against the sentence it sits in before it becomes a
finding, and the sentence is carried into the report so a reader can disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .segment import Clause, locate, normalise, segment

# -- obligation patterns ---------------------------------------------------

ATTRIBUTION = "attribution"
DISCLOSE_SOURCE = "disclose-source"
PATENT_GRANT = "patent-grant"
PATENT_RETALIATION = "patent-retaliation"
NO_WARRANTY = "no-warranty"
NO_LIABILITY = "no-liability"
STATE_CHANGES = "state-changes"
NO_TRADEMARK = "no-trademark"
NETWORK_COPYLEFT = "network-copyleft"
SAME_LICENCE = "same-licence"

OBLIGATIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    ATTRIBUTION: (
        "You must keep the copyright notice",
        "low",
        (
            "above copyright notice",
            "retain the above copyright",
            "must retain",
            "include a copy of this license",
            "reproduce the above copyright",
        ),
    ),
    DISCLOSE_SOURCE: (
        "You must publish your source when you distribute",
        "high",
        (
            "make the source code",
            "accompany it with the complete",
            "corresponding source",
            "must be made available under",
            "provide the source code",
        ),
    ),
    SAME_LICENCE: (
        "Derived work must carry this same licence",
        "high",
        (
            "under the terms of this license",
            "distribute such modifications",
            "licensed as a whole",
            "must be licensed under",
        ),
    ),
    NETWORK_COPYLEFT: (
        "Running it as a network service counts as distribution",
        "high",
        ("interacting with it remotely", "network", "remote network interaction"),
    ),
    PATENT_GRANT: (
        "You receive a patent licence from the contributors",
        "low",
        ("grant of patent license", "patent license", "patent claims licensable"),
    ),
    PATENT_RETALIATION: (
        "Your patent licence ends if you sue over patents",
        "medium",
        (
            "patent litigation",
            "cross-claim or counterclaim",
            "shall terminate as of the date",
        ),
    ),
    STATE_CHANGES: (
        "You must mark files you changed",
        "medium",
        ("carry prominent notices stating that you changed", "modified files to carry"),
    ),
    NO_TRADEMARK: (
        "No right to use the licensor's name or marks",
        "low",
        ("trade names, trademarks", "shall not be used to endorse", "name of the copyright"),
    ),
    NO_WARRANTY: (
        "Supplied with no warranty",
        "low",
        ('"as is" without warranty', "without warranty of any kind", "as is basis"),
    ),
    NO_LIABILITY: (
        "The author accepts no liability",
        "low",
        ("in no event shall", "shall not be liable", "liable for any claim"),
    ),
}

# -- licence families ------------------------------------------------------

# Order matters. The first family whose phrase is found and survives the
# context check wins, so the *specific* licences must be tried before the
# generic keyword that other licences quote.
#
# PSF sits above GPL because of a real misclassification in this corpus: the
# Python licence bundled with `typing_extensions` mentions "GNU General Public
# License" inside a choice-of-law clause about Python 1.6.1, and a keyword
# classifier reads the whole file as GPL. Putting PSF first fixes the cause;
# the disqualifier below catches the same shape elsewhere.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "PSF",
        (
            "this license agreement is between the python software foundation",
            "psf license version",
            "psf hereby grants",
        ),
    ),
    ("AGPL-3.0", ("gnu affero general public license",)),
    ("LGPL", ("gnu lesser general public license", "lesser general public license")),
    ("MPL-2.0", ("mozilla public license",)),
    ("Apache-2.0", ("apache license",)),
    ("GPL", ("gnu general public license",)),
    ("BSD", ("redistribution and use in source and binary forms",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
    ("CC", ("creative commons",)),
)

# A hit inside one of these is discussing another licence, not adopting it.
_CONTEXT_DISQUALIFIERS = (
    "compatible with",
    "compatibility",
    "is not a",
    "does not",
    "unlike",
    "rather than",
    "instead of",
    "may be distributed under the terms of either",
    "conflict with",
    "for the purposes of",
    # From the PSF choice-of-law clause: "...material that was previously
    # distributed under the GNU General Public License (GPL), the law of the
    # Commonwealth of Virginia shall govern..."
    "previously distributed under",
    "notwithstanding the foregoing",
    "with regard to derivative works based on",
    "shall govern",
)


@dataclass(frozen=True)
class Citation:
    """A claim, and exactly where in the source it came from."""

    phrase: str
    start: int
    end: int
    sentence: str
    clause: str

    @property
    def located(self) -> bool:
        return self.start >= 0


@dataclass
class Finding:
    obligation: str
    description: str
    risk: str
    citation: Citation


@dataclass
class Reading:
    path: str
    family: str
    family_citation: Citation | None
    findings: list[Finding] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    @property
    def obligations(self) -> set[str]:
        return {f.obligation for f in self.findings}

    @property
    def copyleft(self) -> bool:
        return bool(self.obligations & {DISCLOSE_SOURCE, SAME_LICENCE, NETWORK_COPYLEFT})

    def high_risk(self) -> list[Finding]:
        return [f for f in self.findings if f.risk == "high"]


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n\n", 0, start))
    right = text.find(".", end)
    return text[left + 1 : right + 1 if right != -1 else len(text)].strip()


def _disqualified(sentence: str) -> str | None:
    lowered = sentence.lower()
    for marker in _CONTEXT_DISQUALIFIERS:
        if marker in lowered:
            return marker
    return None


def _clause_at(clauses: list[Clause], offset: int) -> str:
    for clause in clauses:
        if clause.start <= offset < clause.end:
            return clause.heading
    return "(document)"


def read(path: str, raw: str) -> Reading:
    """Read one licence. Every finding carries the span it came from."""
    text = normalise(raw)
    lowered = text.lower()
    clauses = segment(text)

    family = "unknown"
    family_citation: Citation | None = None
    rejected: list[tuple[str, str]] = []

    for name, phrases in FAMILIES:
        matched = False
        for phrase in phrases:
            span = locate(lowered, phrase)
            if span is None:
                continue
            sentence = _sentence_around(text, *span)
            disqualifier = _disqualified(sentence)
            if disqualifier:
                # The real case: the PSF licence names the GPL in a
                # compatibility clause and a keyword match calls it GPL.
                rejected.append(
                    (name, f"'{phrase}' appears inside '{disqualifier}': {sentence[:110]}")
                )
                continue
            family = name
            family_citation = Citation(
                phrase=phrase,
                start=span[0],
                end=span[1],
                sentence=sentence[:300],
                clause=_clause_at(clauses, span[0]),
            )
            matched = True
            break
        if matched:
            break

    findings: list[Finding] = []
    for key, (description, risk, phrases) in OBLIGATIONS.items():
        for phrase in phrases:
            span = locate(lowered, phrase)
            if span is None:
                continue
            sentence = _sentence_around(text, *span)
            disqualifier = _disqualified(sentence)
            if disqualifier:
                rejected.append((key, f"'{phrase}' inside '{disqualifier}'"))
                continue
            findings.append(
                Finding(
                    obligation=key,
                    description=description,
                    risk=risk,
                    citation=Citation(
                        phrase=phrase,
                        start=span[0],
                        end=span[1],
                        sentence=sentence[:300],
                        clause=_clause_at(clauses, span[0]),
                    ),
                )
            )
            break

    return Reading(
        path=path,
        family=family,
        family_citation=family_citation,
        findings=findings,
        clauses=clauses,
        rejected=rejected,
    )


# -- compatibility ---------------------------------------------------------

PERMISSIVE = frozenset({"MIT", "BSD", "ISC", "Apache-2.0", "Unlicense", "PSF"})
WEAK_COPYLEFT = frozenset({"MPL-2.0", "LGPL"})
STRONG_COPYLEFT = frozenset({"GPL", "AGPL-3.0"})


def conflicts(project_licence: str, dependency: Reading) -> str | None:
    """Why a dependency's licence is a problem for a project under this one.

    Deliberately conservative and deliberately not legal advice. It reports
    the two cases that are not arguable: strong copyleft inside a permissive
    project, and an unidentifiable licence.
    """
    if dependency.family == "unknown":
        return "the licence could not be identified, so its obligations are unknown"
    if project_licence in PERMISSIVE and dependency.family in STRONG_COPYLEFT:
        return (
            f"{dependency.family} requires derived work to be released under the same "
            f"licence, which a {project_licence} project does not do"
        )
    if project_licence in PERMISSIVE and dependency.family in WEAK_COPYLEFT:
        return (
            f"{dependency.family} is file-level copyleft: modifications to its own files "
            f"must stay under {dependency.family}, even inside a {project_licence} project"
        )
    return None
