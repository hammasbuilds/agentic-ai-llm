"""comms-desk against the real AMI Meeting Corpus — all 139 meetings.

`products/data/ami_manual.zip` is AMI's manual annotation set: real recorded
meetings, hand-annotated with dialogue acts and — the part that matters — with
the speaker. A commitment nobody made is not a commitment, and AMI is one of the
few corpora where that attribution is ground truth rather than a diarisation
guess.

These figures were first measured on a twelve-meeting sample, which put the
wrong-merge share at 62%. On the whole corpus it is 87%. The sample was not
merely imprecise, it was *low* — and predictably so, because cross-speaker
collisions are what grows when you add speakers, and twelve meetings held 48
speaker slots against 556. A sample understates this particular failure by
construction, which is the argument for paying the runtime and measuring it all.

Every figure asserted here was produced by running this code over that file.
"""

import pytest

from comms.ami import ARCHIVE, COMMITMENT_ACTS, commitments, utterances
from comms.domain import Commitment, dedupe

pytestmark = pytest.mark.skipif(not ARCHIVE.exists(), reason="AMI corpus not on disk")

THRESHOLDS = (0.5, 0.6, 0.7)


@pytest.fixture(scope="module")
def acts():
    return utterances()


@pytest.fixture(scope="module")
def items(acts):
    found = commitments()
    return [Commitment(f"c{i}", u.key, u.text, "meeting") for i, u in enumerate(found)]


@pytest.fixture(scope="module")
def grid(items):
    """Every merge count, computed once.

    The speaker-blind runs are the expensive half — roughly twenty seconds each,
    because dropping the speaker drops the only barrier that partitions the work.
    Recomputing them per test made this file a multi-minute affair for no gain.
    """
    blind = [Commitment(c.id, "ANY", c.text, c.source) for c in items]
    return {
        (threshold, speaker_blind): len(subject) - len(dedupe(subject, threshold=threshold))
        for threshold in THRESHOLDS
        for speaker_blind, subject in ((False, items), (True, blind))
    }


def test_the_whole_corpus_parses_with_speakers(acts):
    assert len(acts) == 104_923
    assert len({a.meeting for a in acts}) == 139
    assert len({a.key for a in acts}) == 556  # speaker slots, not just speakers
    assert all(a.speaker.isalpha() for a in acts)


def test_only_suggest_and_offer_count_as_commitments(acts, items):
    assert {"sug", "off"} == COMMITMENT_ACTS
    assert len(items) == 10_462
    # Backchannels and stalls are the bulk of a real meeting and commit nobody.
    chatter = [a for a in acts if a.act in {"bck", "stl", "fra"}]
    assert len(chatter) == 29_010
    assert len(chatter) > len(items) * 2


def test_people_rarely_restate_a_commitment_inside_one_meeting(grid, items):
    # Under 1% at a threshold loose enough to catch real restatements. Within a
    # single meeting, saying the same thing twice is uncommon — which is why the
    # duplication this product targets is a CROSS-SOURCE problem.
    assert grid[(0.5, False)] == 100
    assert grid[(0.5, False)] / len(items) < 0.01


def test_dropping_the_speaker_barrier_merges_two_different_people(grid):
    # THE FINDING. At the threshold you need for genuine restatements, ignoring
    # who spoke produces 786 merges of which 686 join two different speakers.
    # Seven out of eight things it merges are wrong.
    with_speaker = grid[(0.5, False)]
    speaker_blind = grid[(0.5, True)]
    assert with_speaker == 100
    assert speaker_blind == 786
    wrong = speaker_blind - with_speaker
    assert wrong == 686
    assert wrong / speaker_blind == pytest.approx(0.873, abs=0.005)


def test_the_sample_understated_it(grid):
    # A twelve-meeting sample said 62%. The whole corpus says 87%. Recorded
    # because the direction is not luck: this failure scales with the number of
    # speakers, so any sample is a floor, never an estimate.
    wrong = grid[(0.5, True)] - grid[(0.5, False)]
    assert wrong / grid[(0.5, True)] > 0.62


def test_tightening_the_threshold_does_not_rescue_it(grid):
    # Tighten the threshold and the wrong merges shrink — along with the right
    # ones, and never fast enough. Even at 0.7, where the barrier keeps only 24
    # merges, going speaker-blind still gets 65 of its 89 merges wrong.
    for threshold in THRESHOLDS:
        blind = grid[(threshold, True)]
        wrong = blind - grid[(threshold, False)]
        assert wrong / blind > 0.7, threshold
    assert grid[(0.7, False)] == 24
    assert grid[(0.7, True)] == 89


def test_speaker_is_a_barrier_not_a_weighted_feature():
    # No threshold, however loose, merges across speakers.
    pair = [
        Commitment(
            "c1", "ayesha", "I will send the revised pricing sheet on Friday", "meeting"
        ),
        Commitment("c2", "bilal", "I will send the revised pricing sheet on Friday", "meeting"),
    ]
    assert len(dedupe(pair, threshold=0.01)) == 2


def test_blocking_changes_speed_and_not_answers(items):
    # dedupe indexes candidates by (speaker, token) instead of scanning every
    # cluster. That is only legitimate if it returns the same clusters, so the
    # pairwise version is kept here and the two are compared on a real slice.
    sample = items[:400]

    def pairwise(subject, threshold):
        clusters: list[list[Commitment]] = []
        for item in subject:
            for cluster in clusters:
                if cluster[0].speaker != item.speaker:
                    continue
                if any(_similar(item, o, threshold) for o in cluster):
                    cluster.append(item)
                    break
            else:
                clusters.append([item])
        return clusters

    for threshold in THRESHOLDS:
        blocked = [[i.id for i in c.items] for c in dedupe(sample, threshold)]
        assert blocked == [[i.id for i in c] for c in pairwise(sample, threshold)]


def _similar(a, b, threshold):
    from comms.domain import similarity

    return similarity(a.text, b.text) >= threshold


def test_a_real_utterance_survives_the_round_trip(items):
    first = items[0]
    assert first.speaker.count(":") == 1  # meeting:speaker
    assert first.text.strip()


def test_a_missing_corpus_is_reported_rather_than_faked():
    from comms.ami import CorpusMissingError

    with pytest.raises(CorpusMissingError):
        utterances(str(ARCHIVE.parent / "nope.zip"))
