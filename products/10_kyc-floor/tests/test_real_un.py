"""kyc-floor's matching rules against a second, independent sanctions list.

Every headline number in this product came off OFAC. A matching rule tuned on
one authority's transliteration habits is a rule about that authority, so the UN
Security Council consolidated list is read here as a check — a different body, a
different listing process, a different mix of regions, and the same kind of
label: 736 individuals carrying 2,163 graded (primary, alias) pairs.

The result is the reason the check was worth running. Measured the way the
README first measured it — over *all* labelled pairs — the two lists disagree
badly: skeletons buy +17.1 points on OFAC and +11.0 on the UN. Measured over the
pairs a string method could possibly reach, they agree to within 1.3 points.
The disagreement was never about the matcher; it was about what fraction of each
list is unreachable by any spelling rule, which is 12% of OFAC and 41% of the UN.

`un_consolidated.xml` is fetched rather than committed, so these skip cleanly
when it is absent.
"""

import random

import pytest

from kycfloor import domain as matching
from kycfloor.un import GOOD, LIST, LOW, individuals, labelled_pairs

pytestmark = pytest.mark.skipif(not LIST.exists(), reason="UN list not on disk")


@pytest.fixture(scope="module")
def pairs():
    return labelled_pairs()


@pytest.fixture(scope="module")
def negatives():
    random.seed(7)
    people = individuals()
    out = []
    while len(out) < 20_000:
        a, b = random.sample(people, 2)
        out.append((a.primary, b.primary))
    return out


def reachable(pair):
    """Whether any spelling rule could link these two names."""
    primary, alias = pair
    return bool(
        {matching.skeleton(t) for t in matching.normalise(primary)}
        & {matching.skeleton(t) for t in matching.normalise(alias)}
    )


def recall(pairs, mode, min_shared=2):
    if not pairs:
        return 0.0
    hits = sum(1 for p, a in pairs if matching.same_person(p, a, mode, min_shared))
    return hits / len(pairs)


def test_the_list_loads():
    people = individuals()
    assert len(people) == 736
    assert all(p.primary for p in people)
    assert all(p.data_id for p in people)


def test_it_carries_graded_ground_truth(pairs):
    assert len(pairs) == 2_163
    assert len(labelled_pairs(quality=GOOD)) == 1_535
    assert len(labelled_pairs(quality=LOW)) == 628


def test_given_name_order_costs_nothing():
    # The UN writes FIRST_NAME..FOURTH_NAME; OFAC writes "SURNAME, Given".
    # normalise() reduces both to an unordered token set, so the two conventions
    # meet. Worth a test rather than an assumption, since every UN figure here
    # would be wrong if it did not hold.
    assert matching.same_person("AYMAN MUHAMMAD RABI AL-ZAWAHIRI", "AL-ZAWAHIRI, Ayman")


def test_far_more_of_this_list_is_unreachable_by_any_spelling_rule(pairs):
    # 41% against OFAC's 12%. Not a defect in either list — the UN records
    # nommes de guerre and single-word aliases that share nothing with a legal
    # name, and that is what a sanctions body is supposed to publish.
    unreachable = [p for p in pairs if not reachable(p)]
    assert len(unreachable) == 885
    assert len(unreachable) / len(pairs) == pytest.approx(0.409, abs=0.01)


def test_the_unreachable_pairs_are_the_ones_the_un_itself_doubts(pairs):
    # THE FINDING this list can produce and OFAC cannot. The UN grades each
    # alias, and "Low" means it is unsure the alias belongs to the person.
    # Three quarters of the Low aliases are unreachable by any spelling rule
    # against a quarter of the Good ones.
    #
    # So the "unmatchable ceiling" is largely a property of weak labels rather
    # than of the matcher, which is exactly what a ceiling should turn out to be.
    def unreachable_share(quality):
        graded = labelled_pairs(quality=quality)
        return sum(1 for p in graded if not reachable(p)) / len(graded)

    assert unreachable_share(LOW) == pytest.approx(0.744, abs=0.01)
    assert unreachable_share(GOOD) == pytest.approx(0.272, abs=0.01)
    assert unreachable_share(LOW) > unreachable_share(GOOD) * 2.5


def test_measured_over_all_pairs_the_two_lists_disagree(pairs):
    # OFAC: 27.8% -> 44.9%, a gain of 17.1 points.
    # UN:   14.7% -> 25.7%, a gain of 11.0 points.
    # Same rule, same code, two authorities, and a 6-point discrepancy.
    strict = recall(pairs, matching.STRICT)
    skeleton = recall(pairs, matching.SKELETON)
    assert strict == pytest.approx(0.1470, abs=0.002)
    assert skeleton == pytest.approx(0.2566, abs=0.002)
    assert skeleton - strict == pytest.approx(0.110, abs=0.005)


def test_measured_over_reachable_pairs_they_agree(pairs):
    # THE POINT. Restricted to pairs a spelling rule could reach:
    # OFAC 33.4% -> 53.2% (+19.8). UN 24.9% -> 43.4% (+18.6).
    # 1.2 points apart, across two sanctions bodies and two naming conventions.
    #
    # The denominator was the whole disagreement. A recall figure over all
    # labels is partly a measurement of how many unmatchable labels the list
    # happens to contain, which is a fact about the publisher.
    can_reach = [p for p in pairs if reachable(p)]
    strict = recall(can_reach, matching.STRICT)
    skeleton = recall(can_reach, matching.SKELETON)
    assert strict == pytest.approx(0.2488, abs=0.003)
    assert skeleton == pytest.approx(0.4343, abs=0.003)
    assert skeleton - strict == pytest.approx(0.186, abs=0.01)


def test_and_skeletons_are_still_free_here(pairs, negatives):
    # The other half of the OFAC finding, replicated: the recall is bought at
    # one false positive in twenty thousand random different-person pairs.
    strict_fp = sum(1 for a, b in negatives if matching.same_person(a, b, matching.STRICT))
    skeleton_fp = sum(1 for a, b in negatives if matching.same_person(a, b, matching.SKELETON))
    assert strict_fp == 0
    assert skeleton_fp == 1


def test_relaxing_further_is_worse_here_than_on_ofac(pairs, negatives):
    # OFAC's "one name part in common" cost 1.74% false positives. On the UN
    # list the same rule costs 7.5% — four times as many — because these names
    # are shorter and share common particles more often. The threshold is not
    # transferable between lists even though the ranking of rules is.
    def fp(mode, min_shared):
        hits = sum(1 for a, b in negatives if matching.same_person(a, b, mode, min_shared))
        return hits / len(negatives)

    assert fp(matching.RELAXED, 2) == pytest.approx(0.0042, abs=0.002)
    assert fp(matching.RELAXED, 1) == pytest.approx(0.0748, abs=0.005)
    assert fp(matching.RELAXED, 1) > 0.04


def test_a_missing_list_is_reported_rather_than_faked():
    from kycfloor.un import ListMissingError

    with pytest.raises(ListMissingError):
        individuals(str(LIST.parent / "nope.xml"))
