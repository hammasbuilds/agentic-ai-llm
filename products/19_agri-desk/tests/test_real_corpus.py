"""agri-desk against the real GenBank corpus.

`products/data/clcuv_full.gb` is 7.5 MB of real Cotton leaf curl virus records
from NCBI — 898 near-complete DNA-A genomes across 23 countries, every
near-full-length genome of the cotton leaf curl complex in the database.

Every number asserted here was produced by running this code over that file.
"""

import pytest

from agridesk.domain import (
    UNKNOWN_SITE,
    collapse_clonal,
    distinct_variants,
    emerging,
    false_alarm_rate,
)
from agridesk.genbank import read
from agridesk.sources import DATA, batches, corpus, isolates, surveillance

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="corpus not on disk")

WINDOW = 4749  # the median collection day in this corpus


def test_the_whole_corpus_parses():
    records = corpus()
    assert len(records) == 898
    assert all(r.sequence for r in records)
    assert all(r.accession for r in records)


def test_geo_loc_name_is_read_not_the_retired_country_field():
    # GenBank renamed /country to /geo_loc_name. Reading only the old name
    # leaves every site "unknown", which silently merges every place into one
    # stratum and breaks both collapsing and emergence.
    sites = {r.site for r in corpus()}
    assert len(sites) == 24  # 23 countries and the unlabelled ones
    assert {"Pakistan", "India", "China", "Burkina Faso", "Sudan"} <= sites


def test_the_documented_eight_genome_submission_is_present():
    # clcuv-surveillance/haplotype.py records this case by accession:
    # ON312781-ON312788, eight genomes, one submission, one field, one
    # haplotype. Still intact after the corpus grew fifteenfold.
    s2 = [r for r in corpus() if r.isolate.startswith("CLCMV/S2-")]
    assert sorted(r.accession for r in s2) == [f"ON3127{n}" for n in range(81, 89)]
    assert {r.submission for r in s2} == {"CLCMV/S"}
    assert len({r.sequence for r in s2}) == 1  # all eight identical


def test_the_neighbouring_submission_is_clonal_too():
    nia = [r for r in corpus() if r.isolate.startswith("CLCMV/NIA-")]
    assert len(nia) == 5
    assert len({r.sequence for r in nia}) == 1


def test_collapsing_removes_the_resequenced_records():
    iso = isolates()
    assert distinct_variants(iso, collapse=False) == 898
    assert distinct_variants(iso, collapse=True) == 795
    # 103 records are a sequence already seen at the same site.


def test_the_largest_clonal_group_is_the_documented_one():
    clonal = sorted((c for c in collapse_clonal(isolates()) if c.clonal), key=lambda c: -c.size)
    assert len(clonal) == 64
    assert [c.size for c in clonal[:7]] == [8, 7, 7, 7, 6, 5, 5]


def test_almost_every_naive_emergence_call_is_spurious():
    # THE FINDING. 436 distinct sequences appear in the window; requiring a variant at
    # more than one site leaves 2.
    #
    # The denominator is asserted, because the README published three different ones -
    # 422 from `min_sites=1`, 427 from nowhere, and 436, which is the only one
    # `false_alarm_rate` actually divides by. 422 is a stricter query than the rate
    # uses and was printed as though it were the rate's candidate count.
    iso = isolates()
    naive = {i.sequence for i in iso if i.day >= WINDOW}
    assert len(naive) == 436, len(naive)
    assert len(emerging(iso, WINDOW, min_sites=1)) == 422
    assert len(emerging(iso, WINDOW, min_sites=2)) == 2
    assert len(naive) - 2 == 434

    # Banded tighter than the digit it guards. `abs=0.002` accepted 0.9934 to 0.9974,
    # twenty times the resolution of the fourth decimal it was checking, so every
    # variant of this figure passed. The published rate is 99.5%, which is the one
    # decimal n=436 supports under `tests/test_rate_precision.py`'s own rule.
    rate = false_alarm_rate(iso, WINDOW, min_sites=2)
    assert rate == pytest.approx(434 / 436, abs=1e-9), rate
    assert f"{rate * 100:.1f}%" == "99.5%", rate


def test_and_the_two_that_survive_are_real():
    # This is what the old 60-genome corpus could not show. There, the filter
    # removed 10 of 10 — and a filter that rejects everything is
    # indistinguishable from a broken one. Here two variants survive, and both
    # are the same sequence found in both Pakistan and India: cross-border
    # spread, which is what emergence in this complex actually looks like.
    iso = isolates()
    survivors = emerging(iso, WINDOW, min_sites=2)
    assert len(survivors) == 2
    for sequence in survivors:
        sites = {i.site for i in iso if i.sequence == sequence}
        assert sites == {"Pakistan", "India"}
    accessions = {i.id for i in iso if i.sequence in survivors}
    assert {"PV769583", "MG373556", "KM096469"} <= accessions


def test_a_third_site_is_a_threshold_nobody_meets():
    assert emerging(isolates(), WINDOW, min_sites=3) == []


def test_an_unlabelled_record_is_not_a_second_site():
    # GenBank omits the country on 31 of the 898 genomes. Counting "unknown" as
    # a place lets a single-site variant reach two sites by being partly
    # unlabelled — the false positive this guard exists to remove, coming back
    # in through the missing-data door. Four variants sit exactly there.
    iso = isolates()
    assert sum(1 for i in iso if i.site == UNKNOWN_SITE) == 31
    by_sequence: dict[str, set[str]] = {}
    for i in iso:
        by_sequence.setdefault(i.sequence, set()).add(i.site)
    borderline = [
        s for s, sites in by_sequence.items() if len(sites) == 2 and UNKNOWN_SITE in sites
    ]
    assert len(borderline) == 4
    reported = set(emerging(iso, 0, min_sites=2))
    assert not [s for s in borderline if s in reported]


def test_receipts_are_one_per_observation_not_one_per_record():
    # Handing the gate 898 receipts for 795 observations is the same
    # double-counting the product exists to catch, moved into the evidence list.
    receipts = surveillance({})
    assert len(receipts) == 795
    assert len(set(receipts)) == 795
    assert all(r in {x.accession for x in corpus()} for r in receipts)


def test_batches_are_the_sampling_unit():
    assert len(batches({})) == 416
    assert "CLCMV/S" in batches({})


def test_a_missing_corpus_is_reported_rather_than_faked():
    from agridesk.sources import CorpusMissingError

    with pytest.raises(CorpusMissingError):
        corpus(str(DATA.parent / "does-not-exist.gb"))


def test_a_record_without_a_sequence_is_skipped_not_guessed():
    text = "LOCUS x\nACCESSION XX000001\nORIGIN\n//\n"
    tmp = DATA.parent / "_tmp_empty.gb"
    tmp.write_text(text, encoding="utf-8")
    try:
        assert read(tmp) == []
    finally:
        tmp.unlink()
