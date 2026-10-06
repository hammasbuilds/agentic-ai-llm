import pytest

from ward.domain import Event, Sentence, active_medications, cite_or_drop, discontinued


def stream():
    return [
        Event("evt_2231", 1, "ordered", "ceftriaxone"),
        Event("evt_2288", 2, "discontinued", "ceftriaxone"),
        Event("evt_2301", 3, "ordered", "co-amoxiclav"),
    ]


def test_a_discontinued_drug_is_not_active():
    assert [a.drug for a in active_medications(stream())] == ["co-amoxiclav"]


def test_every_active_drug_names_the_event_that_ordered_it():
    (active,) = active_medications(stream())
    assert active.evidence == "evt_2301"


def test_reordering_a_stopped_drug_makes_it_active_again():
    events = stream() + [Event("evt_2400", 4, "ordered", "ceftriaxone")]
    assert {a.drug for a in active_medications(events)} == {"ceftriaxone", "co-amoxiclav"}


def test_order_comes_from_the_sequence_not_the_list():
    shuffled = list(reversed(stream()))
    assert [a.drug for a in active_medications(shuffled)] == ["co-amoxiclav"]


def test_discontinued_is_what_a_summary_must_not_name():
    assert discontinued(stream()) == {"ceftriaxone"}


def test_an_unknown_event_kind_is_refused():
    with pytest.raises(ValueError):
        Event("evt_1", 1, "amended", "aspirin")


def test_an_uncited_sentence_is_dropped_before_the_clinician_sees_it():
    draft = cite_or_drop(
        [
            Sentence("Started on co-amoxiclav.", ("evt_2301",)),
            Sentence("The patient tolerated treatment well."),
        ],
        stream(),
    )
    assert len(draft.kept) == 1
    assert draft.dropped[0].text.startswith("The patient tolerated")


def test_a_sentence_citing_an_event_from_another_encounter_is_dropped():
    draft = cite_or_drop([Sentence("Anything.", ("evt_9999",))], stream())
    assert draft.kept == []


def test_one_good_citation_does_not_excuse_one_invented_one():
    draft = cite_or_drop([Sentence("Mixed.", ("evt_2301", "evt_9999"))], stream())
    assert draft.kept == []


def test_drop_rate_is_reported():
    draft = cite_or_drop([Sentence("a", ("evt_2301",)), Sentence("b"), Sentence("c")], stream())
    assert draft.drop_rate == pytest.approx(2 / 3)
