"""hire-desk's redaction barrier, measured on real conversation.

`products/data/locomo10.json` is ten long conversations between named people,
talking the way people do — which means short forms. Every figure asserted here
was produced by running this code over that file.
"""

import pytest

from hiredesk.leaks import (
    BENCHMARK,
    REDACTED,
    audit,
    conversations,
    leak_rate,
    redact_exact,
    survivors,
)

pytestmark = pytest.mark.skipif(not BENCHMARK.exists(), reason="LoCoMo not on disk")


@pytest.fixture(scope="module")
def results():
    return audit()


def test_the_corpus_loads():
    convs = conversations()
    assert len(convs) == 10
    assert sum(c.turns for c in convs) == 5_882
    assert all(len(c.speakers) == 2 for c in convs)


def test_exact_redaction_removes_a_lot(results):
    assert sum(r.exact_removed for r in results) == 1_971


def test_and_still_leaves_the_person_identifiable(results):
    # THE FINDING. Removing every exact occurrence of the name leaves three
    # conversations in ten where the person is still plainly identifiable.
    assert leak_rate() == pytest.approx(0.30, abs=0.01)
    leaked = [r for r in results if r.leaked]
    assert len(leaked) == 3


def test_the_short_form_can_be_more_common_than_the_name(results):
    # "Mel" survives 59 times after "Melanie" was redacted. Someone reading the
    # blinded document does not need the full name.
    by_short = {
        (leak.speaker, leak.survived): leak.occurrences for r in results for leak in r.leaks
    }
    assert by_short[("Melanie", "Mel")] == 59
    assert by_short[("Deborah", "Deb")] == 41
    assert by_short[("Calvin", "Cal")] == 25


def test_a_common_word_sharing_a_prefix_is_not_a_leak():
    # "Nature" shares three characters with "Nate" and is not a name. The
    # detector separates them by whether the word ever appears lower case,
    # which needs no dictionary and no hand-listed diminutives.
    text = "I love nature. Nature is great. Hey Nat, are you coming?"
    found = {leak.survived for leak in survivors(text, ("Nate",))}
    assert "Nature" not in found
    assert "Nat" in found


def test_the_strict_detector_finds_a_third_as_much():
    # Requiring the short form to follow a greeting is unambiguous and misses
    # most of it. Stating which detector produced a number matters more than
    # the number.
    strict = 0
    for conversation in conversations():
        redacted, _ = redact_exact(conversation.text, conversation.speakers)
        if survivors(redacted, conversation.speakers, vocative_only=True):
            strict += 1
    assert strict == 1


def test_redaction_actually_replaces():
    text = "Melanie said hello to Melanie."
    out, removed = redact_exact(text, ("Melanie",))
    assert removed == 2
    assert "Melanie" not in out
    assert out.count(REDACTED) == 2


def test_redaction_is_case_insensitive():
    out, removed = redact_exact("melanie and MELANIE", ("Melanie",))
    assert removed == 2
    assert "melanie" not in out.lower().replace(REDACTED, "")


def test_a_missing_corpus_is_reported_rather_than_faked():
    from hiredesk.leaks import BenchmarkMissingError

    with pytest.raises(BenchmarkMissingError):
        conversations(str(BENCHMARK.parent / "nope.json"))
