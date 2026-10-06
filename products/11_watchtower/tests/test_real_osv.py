"""watchtower against the real OSV vulnerability database.

`products/data/osv_pypi.zip` is OSV's published export for PyPI: 30,098 real
PyPI advisories across 13,327 packages, each carrying the version ranges it
applies to.

Two things about that file were not what this product assumed. It contains 454
entries from other ecosystems, because a GHSA record can list packages in
several at once. And **39% of it is not vulnerability reports at all** — `MAL-`
records are malicious packages, and the shortcut this product exists to discredit
cannot fire on a single one of them. Every figure asserted here was produced by
running this code over that file.
"""

import pytest

from watchtower.osv import (
    OSV_ZIP,
    Advisory,
    Window,
    installed,
    load,
    version_key,
)

pytestmark = pytest.mark.skipif(not OSV_ZIP.exists(), reason="OSV export not on disk")


@pytest.fixture(scope="module")
def db():
    return load()


@pytest.fixture(scope="module")
def verdicts(db):
    """Every advisory judged at every boundary version known for its package."""
    fp = fn = agree = 0
    for advisories in db.values():
        candidates = set()
        for adv in advisories:
            for window in adv.windows:
                candidates.add(window.introduced)
                if window.fixed:
                    candidates.add(window.fixed)
        for adv in advisories:
            for version in candidates:
                naive, correct = adv.affects_naively(version), adv.affects(version)
                if naive == correct:
                    agree += 1
                elif naive:
                    fp += 1
                else:
                    fn += 1
    return {"agree": agree, "false_positive": fp, "false_negative": fn}


def test_the_database_loads(db):
    assert len(db) == 13_327
    assert sum(len(a) for a in db.values()) == 30_098
    # Filtered to one ecosystem. Without the filter 454 NuGet, Maven, npm,
    # crates.io, RubyGems and Go packages arrive too, and their versions get
    # ordered by a PEP 440-ish key that means nothing for a Go pseudo-version.
    assert {a.ecosystem for v in db.values() for a in v} == {"PyPI"}


def test_the_unfiltered_load_really_does_pull_in_other_ecosystems():
    everything = load(None, None)
    advisories = [a for v in everything.values() for a in v]
    foreign = [a for a in advisories if a.ecosystem != "PyPI"]
    assert len(foreign) == 454
    assert {a.ecosystem for a in foreign} >= {"npm", "Maven", "NuGet", "crates.io"}


def test_two_fifths_of_the_database_is_malicious_packages_not_vulnerabilities(db):
    advisories = [a for v in db.values() for a in v]
    malicious = [a for a in advisories if a.malicious]
    assert len(malicious) == 11_734
    assert len(malicious) / len(advisories) == pytest.approx(0.390, abs=0.01)
    # A MAL- record is a typosquat or a backdoored release. The remedy is
    # removal, not an upgrade, so there is nothing to be "below".
    assert sum(1 for a in malicious if a.has_fix) == 5


def test_the_shortcut_cannot_fire_on_a_malicious_package(db):
    # THE SHARPER FINDING. Restricted to MAL- records the shortcut is wrong
    # 99.8% of the time, and every single error is a MISS. It has no false
    # positives here because it never fires at all: no fixed version exists to
    # be below, so `affects_naively` returns False for every malicious package
    # in the database.
    #
    # "Wrong 15% of the time" understates this. For two fifths of OSV the
    # shortcut is not inaccurate, it is structurally incapable of an alert.
    fp = fn = agree = 0
    for advisories in db.values():
        malicious = [a for a in advisories if a.malicious]
        if not malicious:
            continue
        candidates = set()
        for adv in malicious:
            for window in adv.windows:
                candidates.add(window.introduced)
                if window.fixed:
                    candidates.add(window.fixed)
        for adv in malicious:
            for version in candidates:
                naive, correct = adv.affects_naively(version), adv.affects(version)
                if naive == correct:
                    agree += 1
                elif naive:
                    fp += 1
                else:
                    fn += 1
    total = fp + fn + agree
    assert total == 6_415
    assert fp == 0
    assert fn / total == pytest.approx(0.998, abs=0.002)


def test_a_real_vulnerability_usually_does_have_a_fix(db):
    # The contrast that makes the MAL number mean something: where a fix can
    # exist, it usually does, so the shortcut at least fires.
    advisories = [a for v in db.values() for a in v]
    for kind, expected in (("GHSA", 0.073), ("PYSEC", 0.120)):
        group = [a for a in advisories if a.kind == kind]
        without = sum(1 for a in group if not a.has_fix)
        assert without / len(group) == pytest.approx(expected, abs=0.02), kind


def test_versions_order_numerically():
    assert version_key("1.10.0") > version_key("1.9.0")
    assert version_key("2026.7.22") > version_key("2025.1.1")


def test_a_window_is_half_open():
    window = Window("0.10.0", "0.11.1")
    assert not window.covers("0.9.9")  # before the bug was written
    assert window.covers("0.10.0")  # the version it was introduced in
    assert window.covers("0.11.0")
    assert not window.covers("0.11.1")  # the fix itself is not affected


def test_an_unfixed_window_stays_open():
    assert Window("1.0", None).covers("99.0")


def test_the_shortcut_flags_versions_written_before_the_bug():
    # The concrete case, from a real advisory: open-webui GHSA-2724-6cpj-gf3v
    # affects 0.10.0 up to 0.11.1. Version 0.6.19 predates the vulnerability
    # entirely, and "below the highest fixed version" calls it vulnerable.
    adv = Advisory(
        id="GHSA-2724-6cpj-gf3v",
        package="open-webui",
        summary="",
        windows=[Window("0.10.0", "0.11.1")],
    )
    assert adv.highest_fixed == "0.11.1"
    assert adv.affects_naively("0.6.19")
    assert not adv.affects("0.6.19")


def test_the_shortcut_is_wrong_one_time_in_six(verdicts):
    # THE FINDING. 2.1 million verdicts over 30,098 real advisories.
    total = sum(verdicts.values())
    assert total == 2_146_007
    wrong = verdicts["false_positive"] + verdicts["false_negative"]
    assert wrong / total == pytest.approx(0.1541, abs=0.005)


def test_the_headline_survives_dropping_the_malicious_records(db):
    # Worth checking, since MAL- records are 39% of the database and 99.8%
    # wrong: is the 15.4% just malware? No. On vulnerability reports alone it
    # is 15.2%, because MAL- advisories carry very few version boundaries and
    # so contribute only 6,415 of 2.1 million verdicts.
    #
    # The two findings are independent: the range logic matters for real
    # vulnerabilities, and the shortcut is blind to malicious packages.
    fp = fn = agree = 0
    for advisories in db.values():
        real = [a for a in advisories if not a.malicious]
        if not real:
            continue
        candidates = set()
        for adv in real:
            for window in adv.windows:
                candidates.add(window.introduced)
                if window.fixed:
                    candidates.add(window.fixed)
        for adv in real:
            for version in candidates:
                naive, correct = adv.affects_naively(version), adv.affects(version)
                if naive == correct:
                    agree += 1
                elif naive:
                    fp += 1
                else:
                    fn += 1
    total = fp + fn + agree
    assert (fp + fn) / total == pytest.approx(0.1516, abs=0.005)


def test_it_errs_overwhelmingly_towards_false_alarms(verdicts):
    total = sum(verdicts.values())
    assert verdicts["false_positive"] / total == pytest.approx(0.142, abs=0.01)
    assert verdicts["false_negative"] / total == pytest.approx(0.012, abs=0.005)
    assert verdicts["false_positive"] > verdicts["false_negative"] * 8


def test_a_version_between_two_windows_is_the_false_negative_case():
    # Two maintained branches: fixed in 1.2, broken again in 2.0, fixed in 2.1.
    # 2.0 is above the highest fixed version, so the shortcut clears it.
    adv = Advisory(
        id="x",
        package="p",
        summary="",
        windows=[Window("1.0", "1.2"), Window("2.0", "2.1")],
    )
    assert adv.affects("2.0")
    assert not adv.affects_naively("2.2")
    assert adv.affects_naively("1.1")


def test_this_machine_is_scannable(db):
    here = installed()
    assert len(here) > 10
    covered = [p for p in here if p in db]
    assert covered, "expected at least one installed package to carry an advisory"


def test_the_readme_quotes_the_scan_it_ran(db):
    """`assert len(here) > 10` held for 32 packages and for 71 alike.

    So the README went on saying "32 installed packages found 14 carrying advisories"
    while the virtualenv had grown to 71 and 31 - and the floor underneath it could not
    tell the difference. The population moves with the environment, which is why the
    README carries a date; what must not drift silently is the three numbers beside it.
    """
    import re
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    stated = re.search(
        r"(\d+) installed\s+packages found (\d+) carrying advisories"
        r" and (\d+)\s+genuine findings",
        readme.replace(chr(10), " "),
    )
    assert stated, "the README no longer states the scan"
    said_installed, said_covered, said_findings = (int(g) for g in stated.groups())

    here = installed()
    covered = [p for p in here if p in db]
    findings = [adv for package in covered for adv in db[package] if adv.affects(here[package])]
    assert (said_installed, said_covered, said_findings) == (
        len(here),
        len(covered),
        len(findings),
    ), (
        f"the README says {said_installed}/{said_covered}/{said_findings}; the scan "
        f"finds {len(here)}/{len(covered)}/{len(findings)}"
    )

    # And the agreement, which is the finding rather than the population.
    agreed = [adv for adv in findings if adv.affects_naively(here[adv.package])]
    assert len(agreed) == len(findings), (
        f"{len(findings) - len(agreed)} finding(s) the shortcut missed; the README says "
        "the two agreed on all of them"
    )
    assert f"agreed on all {len(findings)}" in readme


def test_a_missing_database_is_reported_rather_than_faked():
    from watchtower.osv import DatabaseMissingError

    with pytest.raises(DatabaseMissingError):
        load(str(OSV_ZIP.parent / "nope.zip"))
