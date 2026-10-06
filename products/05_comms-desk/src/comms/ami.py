"""Reading the AMI Meeting Corpus, and pulling speaker-attributed commitments out of it.

`products/data/ami_manual.zip` is the AMI manual annotations: real recorded
meetings, hand-annotated with dialogue acts, and — the part that matters here —
**attributed to a speaker**. A commitment nobody made is not a commitment, and
AMI is one of the few corpora where the attribution is ground truth rather than
a diarisation guess.

The format is NITE XML: dialogue acts live in one file per (meeting, speaker)
and point at ranges of word ids in another. Speaker identity is in the filename,
which is why it survives even when a range fails to resolve.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

DATA = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA / "ami_manual.zip"

NITE = "{http://nite.sourceforge.net/}"

# The dialogue acts that carry a commitment or a proposal. AMI's own vocabulary:
# `sug` is Suggest, `off` is Offer, `inf` is Inform. Backchannels, stalls and
# fragments are explicitly not commitments and are excluded by not being listed.
COMMITMENT_ACTS = {"sug", "off"}
INFORM_ACTS = {"inf"}

# "ES2016a.D.dialog-act.xml" -> meeting ES2016a, speaker D
_NAME = re.compile(r"^(?P<meeting>[A-Za-z0-9]+)\.(?P<speaker>[A-Z])\.")
_RANGE = re.compile(r"#id\((?P<start>[^)]+)\)(?:\.\.id\((?P<end>[^)]+)\))?")
_ACT = re.compile(r"#id\((?P<id>[^)]+)\)")


class CorpusMissingError(FileNotFoundError):
    """The AMI annotations are not on disk."""


@dataclass(frozen=True)
class Utterance:
    meeting: str
    speaker: str
    act: str
    text: str

    @property
    def is_commitment(self) -> bool:
        return self.act in COMMITMENT_ACTS

    @property
    def key(self) -> str:
        """Who said it, in which meeting. Speaker is never dropped."""
        return f"{self.meeting}:{self.speaker}"


@lru_cache(maxsize=1)
def _act_names(archive: str | None = None) -> dict[str, str]:
    """ami_da_6 -> 'sug'."""
    path = Path(archive) if archive else ARCHIVE
    with zipfile.ZipFile(path) as zf:
        raw = zf.read("ontologies/da-types.xml")
    root = ET.fromstring(raw)
    out: dict[str, str] = {}
    for node in root.iter("da-type"):
        ident = node.get(f"{NITE}id")
        name = node.get("name")
        if ident and name:
            out[ident] = name
    return out


def _words(zf: zipfile.ZipFile, member: str) -> dict[str, str]:
    """Word id -> token, for one (meeting, speaker) file."""
    try:
        root = ET.fromstring(zf.read(member))
    except (KeyError, ET.ParseError):
        return {}
    out: dict[str, str] = {}
    for node in root:
        ident = node.get(f"{NITE}id")
        if not ident:
            continue
        if node.tag == "w" and node.text:
            out[ident] = node.text
    return out


def _span(words: dict[str, str], href: str) -> str:
    """Resolve a NITE word range to text.

    Ranges are inclusive and the ids are sequential with a numeric suffix, so
    the span is reconstructed by counting rather than by following pointers.
    """
    match = _RANGE.search(href or "")
    if not match:
        return ""
    start, end = match.group("start"), match.group("end") or match.group("start")
    keys = list(words)
    try:
        lo, hi = keys.index(start), keys.index(end)
    except ValueError:
        return words.get(start, "")
    return " ".join(words[k] for k in keys[lo : hi + 1] if k in words)


@lru_cache(maxsize=1)
def utterances(archive: str | None = None, limit_meetings: int = 0) -> tuple[Utterance, ...]:
    """Every annotated dialogue act, with its speaker and its text."""
    path = Path(archive) if archive else ARCHIVE
    if not path.exists():
        raise CorpusMissingError(f"{path} is missing. Fetch the AMI manual annotations.")

    names = _act_names(archive)
    out: list[Utterance] = []
    with zipfile.ZipFile(path) as zf:
        members = sorted(
            n
            for n in zf.namelist()
            if n.startswith("dialogueActs/") and n.endswith(".dialog-act.xml")
        )
        seen_meetings: set[str] = set()
        for member in members:
            stem = member.split("/")[-1]
            match = _NAME.match(stem)
            if not match:
                continue
            meeting, speaker = match.group("meeting"), match.group("speaker")
            if limit_meetings:
                if meeting not in seen_meetings and len(seen_meetings) >= limit_meetings:
                    continue
                seen_meetings.add(meeting)

            words = _words(zf, f"words/{meeting}.{speaker}.words.xml")
            if not words:
                continue
            try:
                root = ET.fromstring(zf.read(member))
            except ET.ParseError:
                continue

            for dact in root.iter("dact"):
                act = ""
                text = ""
                for child in dact:
                    href = child.get("href", "")
                    if child.tag == f"{NITE}pointer":
                        found = _ACT.search(href)
                        if found:
                            act = names.get(found.group("id"), "")
                    elif child.tag == f"{NITE}child":
                        text = _span(words, href)
                if act and text:
                    out.append(Utterance(meeting, speaker, act, text))
    return tuple(out)


def commitments(archive: str | None = None, limit_meetings: int = 0) -> list[Utterance]:
    """Suggest and Offer acts — the ones that put someone on the hook."""
    return [u for u in utterances(archive, limit_meetings) if u.is_commitment]
