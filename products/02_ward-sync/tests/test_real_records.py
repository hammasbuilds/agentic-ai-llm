"""ward-sync against real Synthea patient records.

`products/data/synthea_csv.zip` is Synthea's published sample — openly
available, no credentialing. Medications carry a START and a STOP, so a drug
that was discontinued is visible as an event rather than as an absence.

Every figure asserted here was produced by running this code over that file.
"""

import statistics

import pytest

from ward.domain import Event, Sentence, active_medications, cite_or_drop, discontinued
from ward.synthea import ARCHIVE, discrepancies, encounters, medications

pytestmark = pytest.mark.skipif(not ARCHIVE.exists(), reason="Synthea sample not on disk")


@pytest.fixture(scope="module")
def meds():
    return medications()


@pytest.fixture(scope="module")
def gaps():
    return discrepancies()


def test_the_records_load(meds):
    assert len(meds) == 3_850
    assert len(encounters()) == 5_571
    assert len({m.patient for m in meds}) == 105


def test_almost_every_prescription_is_eventually_stopped(meds):
    stopped = [m for m in meds if m.stopped]
    assert len(stopped) / len(meds) == pytest.approx(0.930, abs=0.01)


def test_a_quarter_of_them_are_a_single_administration(meds):
    same_day = [m for m in meds if m.same_day]
    assert len(same_day) == 1_006
    assert 0.2 < len(same_day) / len(meds) < 0.3


def test_the_naive_list_names_a_stopped_drug_for_almost_every_patient(gaps):
    # THE FINDING. A "current medication list" assembled by asking what was
    # started, and never what was stopped, is wrong for 104 of 105 patients.
    affected = [g for g in gaps if g.would_name_a_stopped_drug]
    assert len(affected) == 104
    # 104 of 105, asserted as the two counts. The rate was published as `> 0.98`,
    # which is satisfied by 105 of 105 as well - and the one gap that is NOT affected
    # is the whole reason this is a share rather than "all of them".
    assert (len(affected), len(gaps)) == (104, 105)


def test_the_naive_list_is_five_times_too_long(gaps):
    affected = [g for g in gaps if g.would_name_a_stopped_drug]
    median = statistics.median(g.overstatement for g in affected)
    assert median == pytest.approx(5.54, abs=0.2)


def test_reading_the_event_stream_is_the_fix():
    # The same question on an encounter's events, which is what this product
    # actually does: ordered, ceftriaxone stopped, co-amoxiclav still in force.
    stream = [
        Event("evt_1", 1, "ordered", "ceftriaxone"),
        Event("evt_2", 2, "discontinued", "ceftriaxone"),
        Event("evt_3", 3, "ordered", "co-amoxiclav"),
    ]
    assert [a.drug for a in active_medications(stream)] == ["co-amoxiclav"]
    assert discontinued(stream) == {"ceftriaxone"}


def test_a_real_patient_rebuilds_correctly(meds):
    # Take the busiest real patient and rebuild their medication state from
    # START/STOP events rather than from the list of everything started.
    from collections import Counter

    busiest = Counter(m.patient for m in meds).most_common(1)[0][0]
    theirs = [m for m in meds if m.patient == busiest]
    events, seq = [], 0
    for med in sorted(theirs, key=lambda m: m.start):
        seq += 1
        events.append(Event(f"start_{seq}", seq, "ordered", med.description))
        if med.stopped:
            seq += 1
            events.append(Event(f"stop_{seq}", seq, "discontinued", med.description))

    active = {a.drug for a in active_medications(events)}
    naive = {m.description for m in theirs}
    assert active < naive  # strictly fewer
    assert naive - active  # and the difference is non-empty


def test_a_summary_naming_a_stopped_drug_is_dropped_before_review():
    stream = [
        Event("evt_1", 1, "ordered", "ceftriaxone"),
        Event("evt_2", 2, "discontinued", "ceftriaxone"),
    ]
    draft = cite_or_drop(
        [
            Sentence("Ceftriaxone was stopped after a documented rash.", ("evt_2",)),
            Sentence("The patient continues on ceftriaxone."),
        ],
        stream,
    )
    assert len(draft.kept) == 1
    assert draft.dropped[0].text.endswith("continues on ceftriaxone.")


def test_missing_records_are_reported_rather_than_faked():
    from ward.synthea import RecordsMissingError

    with pytest.raises(RecordsMissingError):
        medications(str(ARCHIVE.parent / "nope.zip"))


# -- the branch that reads the records, not the records themselves -------------


def test_the_agent_reads_one_patients_records_when_no_events_are_supplied(meds):
    """`agents._events` has two branches and only one was ever run.

    Every test in `test_domain.py` and `test_graph.py` supplies `events`, so the
    `state.get("events") is not None` branch is the tested one; the other rebuilds the
    stream from Synthea. Mutating `m.patient == patient` to `!=` on that path returns
    every OTHER patient's medications - 3,814 of them instead of 36 - and the whole
    suite stayed green, including this file, which tested the data layer underneath it.
    """
    from ward import agents

    patient = sorted({m.patient for m in meds})[0]
    theirs = [m for m in meds if m.patient == patient]
    assert theirs, patient

    out = agents.triage({"patient": patient, "encounter": "e1"})
    drugs = set(out["active_medications"]) | set(out["must_not_mention"])
    assert drugs, "the Synthea branch produced no medications at all"
    assert drugs <= {m.description for m in theirs}, (
        "the agent returned a medication this patient was never prescribed, so the "
        "patient filter is reading the wrong rows"
    )


def test_asking_for_no_patient_picks_one_rather_than_mixing_them(meds):
    """`patient is None` takes the first row's patient and filters to it. Without that
    second filter the stream is 105 patients' prescriptions interleaved, and
    `active_medications` is a list no single person was ever on."""
    from ward import agents

    out = agents.triage({"encounter": "e1"})
    drugs = set(out["active_medications"]) | set(out["must_not_mention"])
    assert drugs

    by_patient = {}
    for m in meds:
        by_patient.setdefault(m.patient, set()).add(m.description)
    assert any(drugs <= theirs for theirs in by_patient.values()), (
        "the medications returned do not all belong to any one patient"
    )


def test_a_discontinued_drug_is_in_must_not_mention_on_the_real_branch(meds):
    """The product's whole claim, over records rather than a fixture."""
    from ward import agents

    patient = next(
        (
            m.patient
            for m in meds
            if m.stopped and any(o.patient == m.patient and not o.stopped for o in meds)
        ),
        None,
    )
    if patient is None:
        pytest.skip("no patient in the sample has both a stopped and an active drug")

    out = agents.triage({"patient": patient, "encounter": "e1"})
    assert out["must_not_mention"], patient
    assert not set(out["must_not_mention"]) & set(out["active_medications"]), (
        "a drug is both discontinued and active, so the event stream is being read out of order"
    )
