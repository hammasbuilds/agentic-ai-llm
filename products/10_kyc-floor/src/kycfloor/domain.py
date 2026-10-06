"""Are these two spellings the same name.

Not a language-understanding problem. The same Urdu or Arabic name reaches a
sanctions list through several transliteration conventions and several byte
encodings that render identically, and normalising for that is arithmetic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PARTICLES = frozenset({"al", "el", "bin", "ibn", "bint", "abu", "ab", "ul", "ud", "uz", "us"})

# Honorifics and ranks. A title is not a name part, and leaving one in breaks
# subset matching for everyone who happens to carry it: "AL ZAWAHIRI, Dr. Ayman"
# and "AL-ZAWAHIRI, Ayman Muhammad Rabi" fail to match on `dr` alone.
TITLES = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "miss",
        "prof",
        "professor",
        "sir",
        "shaykh",
        "sheikh",
        "shaikh",
        "hajji",
        "haji",
        "hajj",
        "mullah",
        "maulana",
        "imam",
        "sayyid",
        "sayed",
        "engineer",
        "eng",
        "general",
        "gen",
        "colonel",
        "col",
        "major",
        "maj",
        "captain",
        "capt",
        "lieutenant",
        "lt",
        "brigadier",
        "brig",
        "commander",
        "cmdr",
        "admiral",
        "minister",
        "president",
        "chairman",
        "the",
        "alias",
    }
)

# Arabic script does not write short vowels, so the vowels in a transliteration
# are the transliterator's choice rather than the name. Comparing consonant
# skeletons is what lets zomor / zumar / zumur / zamur be one name, which is what
# they are.
_VOWELS = frozenset("aeiou")

# Transliteration conventions that reach a list for one underlying name.
EQUIVALENTS: tuple[tuple[str, str], ...] = (
    ("mohammad", "muhammad"),
    ("mohammed", "muhammad"),
    ("muhammed", "muhammad"),
    ("mohamed", "muhammad"),
    ("mohd", "muhammad"),
    ("ph", "f"),
    ("kh", "k"),
    ("gh", "g"),
    ("dh", "d"),
    ("th", "t"),
    ("sh", "s"),
    ("ee", "i"),
    ("oo", "u"),
    ("ou", "u"),
    ("y", "i"),
    ("w", "v"),
)

_NON_LETTER = re.compile(r"[^a-z\s]")
_SPACES = re.compile(r"\s+")

MIN_TOKENS = 2


def fold(token: str) -> str:
    """One token reduced to its transliteration-insensitive form."""
    out = token
    for source, target in EQUIVALENTS:
        out = out.replace(source, target)
    # Collapse doubled letters last: haroon -> harun -> harun, hassan -> hasan.
    collapsed = []
    for char in out:
        if not collapsed or collapsed[-1] != char:
            collapsed.append(char)
    return "".join(collapsed)


PREFIXES = ("al", "el", "ul")


def _drop_leading_particle(token: str) -> str:
    """``alhassan`` -> ``hassan``, but ``ali`` stays ``ali``.

    Deliberately recall-over-precision, and only for these three prefixes. A
    screening miss is a fine; an extra candidate costs an analyst a minute.
    The guard is the remainder length: anything shorter than four characters is
    left alone, which is what keeps ``ali``, ``elm`` and ``ula`` intact.
    """
    for prefix in PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 4:
            return token[len(prefix) :]
    return token


def normalise(name: str) -> tuple[str, ...]:
    """A name as a sorted tuple of folded tokens.

    Sorted because list order varies: "Khan Ayesha" and "Ayesha Khan" are one
    person. Particles are dropped because they are written attached or detached
    at random.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = _NON_LETTER.sub(" ", stripped.lower().replace("-", " "))
    tokens = [t for t in _SPACES.split(cleaned) if t and t not in PARTICLES and t not in TITLES]
    return tuple(sorted({_drop_leading_particle(fold(t)) for t in tokens if t}))


def skeleton(token: str) -> str:
    """The consonant skeleton of a folded token.

    ``zomor`` -> ``zmr``; ``havatmeh`` -> ``hvtmh``; ``jabril`` -> ``jbrl``. A
    leading vowel is kept, because dropping it merges names that differ at the
    start, where Arabic transliteration is most stable.
    """
    if not token:
        return token
    head = token[0]
    return head + "".join(c for c in token[1:] if c not in _VOWELS)


STRICT = "strict"
SKELETON = "skeleton"
RELAXED = "relaxed"
MODES = (STRICT, SKELETON, RELAXED)


def same_person(a: str, b: str, mode: str = SKELETON, min_shared: int = 2) -> bool:
    """Whether two spellings name the same party.

    Three modes, because the right answer depends on what a miss costs:

    ``strict``   exact folded tokens, subset either way. Highest precision.
    ``skeleton`` the same, on consonant skeletons. Absorbs transliteration vowels.
    ``relaxed``  skeletons, and ``min_shared`` parts in common is enough — no
                 subset required, so two names that each carry extra parts can
                 still match.

    Screening wants recall: a miss is a fine, a false positive costs an analyst a
    minute. ``skeleton`` is the default because it raises recall a long way at
    almost no cost in precision; ``relaxed`` is the setting to reach for when the
    queue can absorb it.
    """
    if mode not in MODES:
        raise ValueError(f"{mode!r} is not one of {MODES}")
    if min_shared < 1:
        raise ValueError("min_shared must be at least 1")

    na, nb = set(normalise(a)), set(normalise(b))
    if mode is not STRICT and mode != STRICT:
        na = {skeleton(t) for t in na}
        nb = {skeleton(t) for t in nb}

    if len(na) < MIN_TOKENS or len(nb) < MIN_TOKENS:
        return na == nb and len(na) >= MIN_TOKENS

    if mode == RELAXED:
        return len(na & nb) >= min_shared
    return na <= nb or nb <= na


@dataclass(frozen=True)
class Hit:
    listed: str
    matched_on: tuple[str, ...]


def screen(name: str, listed: list[str], mode: str = SKELETON) -> list[Hit]:
    """Every list entry this name could be. Recall first; a human sifts."""
    return [Hit(entry, normalise(entry)) for entry in listed if same_person(name, entry, mode)]


def alias_recall(found: set[str], truth: set[str]) -> float:
    """Share of the real aliases a matcher found. Undefined on an empty truth set."""
    if not truth:
        raise ValueError("recall is undefined with no true aliases")
    return len(found & truth) / len(truth)
