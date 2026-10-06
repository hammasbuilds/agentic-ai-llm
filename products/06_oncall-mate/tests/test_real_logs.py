"""oncall-mate against real production logs.

`products/data/*_2k.log` are Loghub's published samples — all sixteen of them:
Android, Apache, BlueGene/L, Hadoop, HDFS, HealthApp, HPC, Linux, Mac, OpenSSH,
OpenStack, Proxifier, Spark, Thunderbird, Windows and ZooKeeper. Same size, same
templater, sixteen very different systems.

The first version of this read five, which is a thin basis for a claim about a
*spread*. Tripling it confirmed the headline and corrected the middle: the ends
did not move at all, and the median fell from 11.1 to 8.5.

Every figure asserted here was produced by running this code over those files.
"""

import statistics

import pytest

from oncall.domain import Alert, collapse, reduction
from oncall.logs import DATA, SYSTEMS, Line, compression, read, template

pytestmark = pytest.mark.skipif(
    not (DATA / "hdfs_2k.log").exists(), reason="Loghub samples not on disk"
)


@pytest.fixture(scope="module")
def lines():
    return read()


def by_system(lines, system):
    return [line for line in lines if line.system == system]


def test_all_sixteen_systems_load(lines):
    assert len(lines) == 32_000
    assert len(SYSTEMS) == 16
    assert {line.system for line in lines} == set(SYSTEMS)


def test_templating_masks_what_varies_per_occurrence():
    a = template("PacketResponder 1 for block blk_38865049064139660 terminating")
    b = template("PacketResponder 0 for block blk_-6952295868487656571 terminating")
    assert a == b == "PacketResponder <num> for block <blk> terminating"


def test_an_ip_is_not_an_identity():
    assert template("client 10.11.10.1 timed out") == template("client 192.168.0.7 timed out")


def test_the_compression_ratio_spans_two_orders_of_magnitude(lines):
    # THE FINDING. One templater, sixteen identical 2,000-line samples, and the
    # ratio runs from 1.09 to 125. A compression ratio is a property of the log,
    # not of the templater — so a threshold tuned on one system is meaningless
    # on the next.
    ratios = {s: compression(by_system(lines, s)).ratio for s in SYSTEMS}
    assert ratios["hdfs"] == pytest.approx(125.0, abs=0.5)
    assert ratios["bgl"] == pytest.approx(1.09, abs=0.02)
    assert max(ratios.values()) / min(ratios.values()) > 100


def test_tripling_the_systems_did_not_move_the_ends(lines):
    # Worth recording because it is the outcome that does NOT usually follow.
    # A spread taken from five points normally understates itself — fleet-desk's
    # did. Here eleven more systems left both extremes exactly where they were:
    # BlueGene/L is still the floor and HDFS still the ceiling, and none of the
    # newcomers reaches either.
    ratios = {s: compression(by_system(lines, s)).ratio for s in SYSTEMS}
    assert min(ratios, key=ratios.get) == "bgl"
    assert max(ratios, key=ratios.get) == "hdfs"

    original = {"hdfs", "bgl", "hpc", "openstack", "zookeeper"}
    newcomers = [r for s, r in ratios.items() if s not in original]
    assert max(newcomers) < ratios["hdfs"]
    assert min(newcomers) > ratios["bgl"]


def test_but_the_original_five_were_not_a_typical_middle(lines):
    # What the wider sample did change. Three of the first five compressed
    # above 10x; only seven of sixteen do. The median ratio falls from 11.1 to
    # 8.5, so "expect roughly an order of magnitude" was optimistic — most
    # production logs are far less repetitive than HDFS.
    ratios = {s: compression(by_system(lines, s)).ratio for s in SYSTEMS}
    original = {"hdfs", "bgl", "hpc", "openstack", "zookeeper"}

    assert statistics.median(ratios.values()) == pytest.approx(8.48, abs=0.2)
    assert statistics.median([ratios[s] for s in original]) == pytest.approx(11.11, abs=0.2)
    assert sum(1 for r in ratios.values() if r < 10) == 9


def test_hdfs_collapses_two_thousand_messages_into_sixteen(lines):
    c = compression(by_system(lines, "hdfs"))
    assert c.distinct_raw == 2000
    assert c.distinct_templates == 16
    assert c.messages_lost == 1984


def test_bgl_barely_compresses_at_all(lines):
    c = compression(by_system(lines, "bgl"))
    assert c.distinct_templates == 1840
    assert c.ratio < 1.2  # the context problem is not solved here


def test_compression_eats_the_rare_line_first(lines):
    # An incident is made of the message that appeared once. On HDFS, 2,000
    # messages are seen exactly once and 3 templates are; 1,997 singletons stop
    # existing as anything a correlator could point at.
    c = compression(by_system(lines, "hdfs"))
    assert c.raw_seen_once == 2000
    assert c.templates_seen_once == 3
    assert c.rare_lost == 1997


def test_the_corpus_wide_figure_hides_all_of_that(lines):
    # Pooling all sixteen gives 4.49x and looks unremarkable, sitting below the
    # median of the systems it is made of. That is why the per-system table is
    # the result and the pooled number is not.
    c = compression(lines)
    assert c.ratio == pytest.approx(4.49, abs=0.05)
    assert c.rare_lost == 24_458
    ratios = [compression(by_system(lines, s)).ratio for s in SYSTEMS]
    assert c.ratio < statistics.median(ratios)


def test_a_drip_of_real_templates_still_cannot_chain_forever(lines):
    # The transitivity guard, on real templates rather than invented ones.
    hdfs = by_system(lines, "hdfs")[:200]
    alerts = [Alert(f"al_{i}", "hdfs", line.template, i * 100) for i, line in enumerate(hdfs)]
    incidents = collapse(alerts, window=120, max_span=900)
    assert len(incidents) > 1
    assert all(inc.span <= 900 for inc in incidents)
    assert reduction(alerts, incidents) > 0.8


def test_levels_are_read_from_the_line(lines):
    assert Line("hdfs", 0, "081109 203615 148 INFO dfs.DataNode: x").level == "INFO"
    assert Line("bgl", 0, "RAS KERNEL FATAL something broke").level == "FATAL"


def test_missing_logs_are_reported_rather_than_faked():
    from oncall.logs import LogsMissingError

    with pytest.raises(LogsMissingError):
        read(str(DATA / "nowhere"))
