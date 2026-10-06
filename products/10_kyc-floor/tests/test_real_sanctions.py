"""kyc-floor against the real OFAC sanctions list.

`SDN.CSV` and `ALT.CSV` are OFAC's published exports, committed under
`products/data/`. Every (primary name, alias) pair in them is a labelled
positive: two spellings a sanctions authority has already declared to be one
party. That makes alias recall directly measurable on real data, on exactly the
Arabic- and Urdu-origin names this product exists for, with no annotation.

Every figure asserted here was produced by running this code over those files.
"""

import random

import pytest

from kycfloor import domain as matching
from kycfloor.ofac import ALT, SDN, individuals, labelled_pairs, load

pytestmark = pytest.mark.skipif(
    not (SDN.exists() and ALT.exists()), reason="OFAC exports not on disk"
)


@pytest.fixture(scope="module")
def pairs():
    return labelled_pairs()


@pytest.fixture(scope="module")
def negatives():
    """Random different-entity pairs. Two sanctioned people are not one person."""
    random.seed(7)
    people = individuals()
    out = []
    while len(out) < 20_000:
        a, b = random.sample(people, 2)
        out.append((a.primary, b.primary))
    return out


def recall(pairs, mode, min_shared=2):
    return sum(1 for p, a in pairs if matching.same_person(p, a, mode, min_shared)) / len(pairs)


def test_the_lists_load():
    entities = load()
    assert len(entities) == 19_393
    assert len(individuals()) == 7_535


def test_there_is_real_ground_truth(pairs):
    assert len(pairs) == 8_650


def test_a_sixth_of_the_aliases_are_unmatchable_by_any_string_method(pairs):
    # "ABBAS, Abu" and "ZAYDAN, Muhammad" are one man. No spelling rule links
    # them, so this fraction is a ceiling on string matching, not a defect.
    shares_nothing = [
        1 for p, a in pairs if not (set(matching.normalise(p)) & set(matching.normalise(a)))
    ]
    assert len(shares_nothing) == 1_461
    assert 0.16 < len(shares_nothing) / len(pairs) < 0.17

    # Skeletons recover a few of them: two names can share a consonant frame
    # while sharing no identical token.
    no_skeleton = [
        1
        for p, a in pairs
        if not (
            {matching.skeleton(x) for x in matching.normalise(p)}
            & {matching.skeleton(x) for x in matching.normalise(a)}
        )
    ]
    assert len(no_skeleton) == 1_048


def test_titles_are_not_name_parts():
    # "AL ZAWAHIRI, Dr. Ayman" vs "AL-ZAWAHIRI, Ayman Muhammad Rabi" failed on
    # `dr` alone before titles were stripped.
    assert "dr" not in matching.normalise("AL ZAWAHIRI, Dr. Ayman")
    assert matching.same_person("AL ZAWAHIRI, Dr. Ayman", "AL-ZAWAHIRI, Ayman")


def test_consonant_skeletons_absorb_transliteration_vowels():
    # Arabic does not write short vowels, so these are one name spelled four ways.
    assert matching.skeleton("zomor") == matching.skeleton("zumur") == "zmr"
    for variant in ("AL-ZUMAR, Abbud", "AL-ZUMUR, Abood", "AL-ZAMUR, Abboud"):
        assert matching.same_person("AL-ZOMOR, Abboud", variant, matching.SKELETON)


def test_strict_matching_finds_a_third_of_what_it_could(pairs):
    assert recall(pairs, matching.STRICT) == pytest.approx(0.2776, abs=0.001)


def test_skeletons_buy_recall_for_nothing(pairs, negatives):
    # THE FINDING, part one: +19.8 points of recall, and the false-positive
    # rate does not move at all.
    strict_fp = sum(1 for a, b in negatives if matching.same_person(a, b, matching.STRICT))
    skel_fp = sum(1 for a, b in negatives if matching.same_person(a, b, matching.SKELETON))
    assert recall(pairs, matching.SKELETON) == pytest.approx(0.4494, abs=0.001)
    assert strict_fp == skel_fp == 1  # 1 in 20,000, unchanged


def test_every_further_point_of_recall_is_bought_with_precision(pairs, negatives):
    # THE FINDING, part two: past skeletons the trade turns bad, fast.
    assert recall(pairs, matching.RELAXED, 2) == pytest.approx(0.6260, abs=0.001)
    assert recall(pairs, matching.RELAXED, 1) == pytest.approx(0.8754, abs=0.001)

    def fp(min_shared):
        hits = sum(
            1 for a, b in negatives if matching.same_person(a, b, matching.RELAXED, min_shared)
        )
        return hits / len(negatives)

    fp2, fp1 = fp(2), fp(1)
    assert fp2 == pytest.approx(0.00055, abs=0.0002)
    assert fp1 == pytest.approx(0.0174, abs=0.002)
    assert fp1 > fp2 * 25  # the last stretch costs 30x the false-positive load


def test_the_default_mode_is_the_free_one():
    assert matching.same_person.__defaults__[0] == matching.SKELETON


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        matching.same_person("a b", "a b", "vibes")


def test_a_clean_name_still_screens_clean():
    listed = [e.primary for e in individuals()[:2000]]
    assert matching.screen("Zainab Farooq Sheikh", listed) == []
