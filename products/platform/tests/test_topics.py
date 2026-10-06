import pytest

from agentplatform import topics


def test_five_topics_under_one_domain():
    t = topics.Topics("crm")
    assert t.all() == (
        "crm.intake",
        "crm.tasks",
        "crm.events",
        "crm.approvals",
        "crm.dlq",
    )


@pytest.mark.parametrize("bad", ["CRM", "crm_desk", "-crm", "crm--desk", "1crm", ""])
def test_illegal_domains_are_refused(bad):
    with pytest.raises(topics.InvalidDomainError):
        topics.Topics(bad)


def test_unknown_suffix_is_refused():
    with pytest.raises(ValueError):
        topics.Topics("crm").name("retries")


def test_same_entity_always_lands_on_one_partition():
    key = topics.partition_key("deal", "4192")
    assert key == "deal:4192"
    assert len({topics.partition_for(key, 12) for _ in range(50)}) == 1


#: The values `crc32` gives, written down. This is the pin the test below claimed to be.
#:
#: The claim was "this value must not change when PYTHONHASHSEED does. Pinning it is the
#: regression test" over
#:
#:     assert partition_for("deal:4192", 12) == partition_for("deal:4192", 12)
#:     assert partition_for("deal:4192", 1) == 0
#:
#: - a pure function compared with itself, and `x % 1 == 0` for every x. Replacing
#: `zlib.crc32` with the built-in `hash()` left the whole platform suite green, which is
#: the exact regression the comment names. It is the first of `products/README.md`'s
#: "four decisions worth knowing".
PARTITIONS = {
    ("deal:4192", 1): 0,
    ("deal:4192", 3): 2,
    ("deal:4192", 12): 5,
    ("deal:4192", 64): 37,
    ("patient:77", 12): 6,
    ("patient:77", 64): 38,
    ("ticket:abc", 12): 3,
    ("ticket:abc", 64): 31,
}


@pytest.mark.parametrize("key,count", sorted(PARTITIONS), ids=lambda a: str(a))
def test_partitioning_is_stable_across_processes(key, count):
    """The value itself, not an identity.

    `hash()` is salted per process, so a worker and a web process would disagree about
    which partition a key belongs to - and a key's ordering guarantee is exactly that
    they do not.
    """
    assert topics.partition_for(key, count) == PARTITIONS[(key, count)]


def test_the_partition_values_are_the_ones_crc32_gives():
    """Independently of the implementation under test.

    Computed here from `zlib.crc32` directly, so the table above cannot be re-derived
    from a changed `partition_for` and still agree with it.
    """
    import zlib

    for (key, count), expected in PARTITIONS.items():
        assert zlib.crc32(key.encode()) % count == expected, (key, count)


def test_a_single_partition_is_not_evidence_of_anything():
    """`partition_for(k, 1) == 0` was one of the two original assertions. `x % 1` is 0
    for every x, so it holds for `hash()`, for `crc32`, and for a function returning a
    constant. It is kept as documentation of what it does not show."""
    assert topics.partition_for("anything at all", 1) == 0
    assert topics.partition_for("something else", 1) == 0


def test_partition_count_must_be_positive():
    with pytest.raises(ValueError):
        topics.partition_for("deal:1", 0)


def test_partition_key_needs_both_halves():
    with pytest.raises(ValueError):
        topics.partition_key("deal", "")
