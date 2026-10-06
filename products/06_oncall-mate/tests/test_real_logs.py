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


# -- the branch that reads the logs, not the logs themselves -------------------


def test_the_agent_reads_one_systems_lines_when_no_alerts_are_supplied():
    """`agents._alerts` has two branches and only one was ever run.

    Its own docstring says so: "Real log lines unless the caller supplied alerts (the
    unit tests do)." Every test in `test_domain.py` and `test_graph.py` supplies
    `alerts`, so mutating `line.system == system` to `!=` on the other path returns
    every OTHER system's log lines - 30,000 of them from fifteen unrelated systems
    instead of 2,000 from the one asked for - and the whole suite stayed green,
    including this file, which tested the reader underneath it.

    Asserted on `_alerts`, not on `triage`: triage returns counts, so the only thing a
    wrong system shows up in there is the magnitude.
    """
    from oncall import agents

    alerts = agents._alerts({"system": "hdfs"})
    assert alerts, "the Loghub branch produced nothing at all"
    assert {a.service for a in alerts} == {"hdfs"}, sorted({a.service for a in alerts})
    assert all(a.id.startswith("hdfs_") for a in alerts)


def test_each_system_asked_for_is_the_system_returned():
    """Three systems, so a filter that happens to pass one cannot pass by luck."""
    from oncall import agents

    for system in ("hdfs", "spark", "zookeeper"):
        alerts = agents._alerts({"system": system})
        assert alerts, system
        assert {a.service for a in alerts} == {system}, (
            system,
            sorted({a.service for a in alerts}),
        )


def test_the_default_system_is_one_system(monkeypatch):
    """`state.get("system", "hdfs")` - the default must not be "all of them"."""
    from oncall import agents

    assert {a.service for a in agents._alerts({})} == {"hdfs"}


def test_the_limit_bounds_what_the_real_branch_reads():
    """`lines[: state.get("limit", 500)]` is the only thing keeping a 2,000-line sample
    out of a single payload, and the default is what an unparameterised call gets."""
    from oncall import agents

    assert len(agents._alerts({"system": "hdfs", "limit": 5})) == 5
    assert len(agents._alerts({"system": "hdfs", "limit": 200})) == 200
    assert len(agents._alerts({"system": "hdfs"})) == 500


def test_the_real_branch_is_taken_only_when_no_alerts_are_supplied():
    """The other direction: a caller's alerts must not be mixed with the log lines."""
    from oncall import agents

    supplied = agents._alerts(
        {
            "system": "hdfs",
            "alerts": [{"id": "mine_1", "service": "payments", "template": "t", "at": 0}],
        }
    )
    assert [a.id for a in supplied] == ["mine_1"]
    assert {a.service for a in supplied} == {"payments"}


def test_an_alert_is_labelled_with_the_system_its_line_came_from():
    """It was labelled with the system that was ASKED for.

        Alert(f"{system}_{line.n}", system, ...)

    Both fields were the request, so with the filter inverted this function returned
    fifteen other systems' log lines every one of them stamped `hdfs`, and nothing
    downstream - including the three tests above - could tell. A record that cannot say
    where it came from cannot be audited.

    It also made the id ambiguous: `hdfs_41` and `spark_41` are different lines with the
    same number, so two systems' alerts could collide on one key.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "oncall" / "agents.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Alert"
    ]
    assert built, "nothing constructs an Alert any more"
    for call in built:
        if len(call.args) < 2:
            continue
        service = call.args[1]
        # The second argument is the service. From a line, it must be the line's own
        # system - `line.system` - and not the bare `system` the caller asked for.
        if isinstance(service, ast.Name) and service.id == "system":
            raise AssertionError(
                f"agents.py:{call.lineno} labels an Alert with the requested system "
                "rather than the line's own"
            )
