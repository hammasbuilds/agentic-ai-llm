"""Controls: a stated policy, checked against collected evidence.

The rule that shapes everything here: **a control may only return PASS when a
collector actually observed something.** There is no inferred compliance. If a
collector could not look - the repository is not a git checkout, there is no
`pyproject.toml` - the control returns NOT_APPLICABLE or INCONCLUSIVE, never
PASS.

That distinction is the whole point. A policy document that says "all repos
have a licence" and an audit that assumes it because nobody checked are the
same sentence with different consequences.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from .evidence import Evidence

PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "n/a"
INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Result:
    control: str
    status: str
    detail: str
    artefact: str = ""  # where the evidence came from

    @property
    def counted(self) -> bool:
        """Only pass/fail go into a compliance rate."""
        return self.status in (PASS, FAIL)


@dataclass(frozen=True)
class Control:
    id: str
    policy: str  # the claim being checked, in the policy's own words
    check: Callable[[Evidence], Result]


def _result(control: str, status: str, detail: str, artefact: str = "") -> Result:
    return Result(control=control, status=status, detail=detail, artefact=artefact)


# -- README conventions ---------------------------------------------------


def _readme_section(ev: Evidence, cid: str, patterns: tuple[str, ...], label: str) -> Result:
    if ev.readme is None:
        return _result(cid, INCONCLUSIVE, "no README found, so nothing could be checked")
    for heading in ev.headings:
        if any(re.search(p, heading, re.IGNORECASE) for p in patterns):
            return _result(cid, PASS, f"heading: {heading!r}", ev.readme_path or "")
    return _result(
        cid,
        FAIL,
        f"no heading matching {label} among {len(ev.headings)} headings",
        ev.readme_path or "",
    )


def readme_exists(ev: Evidence) -> Result:
    if ev.readme is None:
        return _result("readme-exists", FAIL, "no README file")
    words = len(ev.readme.split())
    if words < 50:
        return _result(
            "readme-exists", FAIL, f"README is {words} words - a stub", ev.readme_path or ""
        )
    return _result("readme-exists", PASS, f"{words} words", ev.readme_path or "")


def readme_limits(ev: Evidence) -> Result:
    return _readme_section(
        ev,
        "readme-limits",
        (r"does\s*not\s*do", r"\blimitations?\b", r"not\s+included", r"out\s+of\s+scope"),
        "'what it does NOT do'",
    )


def readme_problems(ev: Evidence) -> Result:
    return _readme_section(
        ev,
        "readme-problems",
        (r"problems?\s+hit", r"\bproblems?\b", r"what\s+went\s+wrong", r"mistakes"),
        "'problems hit while building this'",
    )


def readme_io(ev: Evidence) -> Result:
    if ev.readme is None:
        return _result("readme-io", INCONCLUSIVE, "no README found")
    has_in = re.search(r"\*\*In:\*\*|^\s*#+\s*Input", ev.readme, re.IGNORECASE | re.MULTILINE)
    has_out = re.search(
        r"\*\*Out:\*\*|^\s*#+\s*Output", ev.readme, re.IGNORECASE | re.MULTILINE
    )
    if has_in and has_out:
        return _result(
            "readme-io", PASS, "states what goes in and what comes out", ev.readme_path or ""
        )
    missing = [n for n, v in (("In", has_in), ("Out", has_out)) if not v]
    return _result("readme-io", FAIL, f"missing: {', '.join(missing)}", ev.readme_path or "")


# -- dependency hygiene ---------------------------------------------------

# Modules importable without being declared: the standard library, plus the
# dev tooling every repo here runs.
#
# A hand-written list was the first attempt and it scored this control at 0%
# across 30 repositories - every repo "failed" because the list was missing
# whatever it happened to import. `sys.stdlib_module_names` is the actual
# answer and is maintained by the interpreter.
_DEV_TOOLS = frozenset({"pytest", "_pytest", "ruff", "conftest", "setuptools", "pip"})
_STDLIB_ISH = frozenset(sys.stdlib_module_names) | _DEV_TOOLS


def _declared_names(ev: Evidence) -> set[str]:
    names: set[str] = set()
    groups = [ev.declared_dependencies, *ev.declared_optional.values()]
    for group in groups:
        for spec in group:
            base = re.split(r"[<>=!~\[\s;]", spec, maxsplit=1)[0].strip().lower()
            if base:
                names.add(base.replace("-", "_"))
    return names


# Import names that differ from the distribution that provides them. Several
# distributions can provide the same import name - `cv2` comes from
# `opencv-python` or `opencv-python-headless` - so each maps to a set and the
# control passes if any of them is declared.
_ALIASES: dict[str, frozenset[str]] = {
    "yaml": frozenset({"pyyaml"}),
    "cv2": frozenset({"opencv_python", "opencv_python_headless", "opencv_contrib_python"}),
    "sklearn": frozenset({"scikit_learn"}),
    "skimage": frozenset({"scikit_image"}),
    "PIL": frozenset({"pillow"}),
    "bs4": frozenset({"beautifulsoup4"}),
    "dotenv": frozenset({"python_dotenv"}),
    "psycopg": frozenset({"psycopg", "psycopg2", "psycopg2_binary"}),
    "psycopg_pool": frozenset({"psycopg", "psycopg_pool"}),
    "dateutil": frozenset({"python_dateutil"}),
    "attr": frozenset({"attrs"}),
    "pkg_resources": frozenset({"setuptools"}),
    "jwt": frozenset({"pyjwt"}),
    "serial": frozenset({"pyserial"}),
    "fitz": frozenset({"pymupdf"}),
    "docx": frozenset({"python_docx"}),
}


def _provides(module: str) -> frozenset[str]:
    """Distribution names that could provide this import."""
    normalised = module.lower().replace("-", "_")
    return _ALIASES.get(module, _ALIASES.get(normalised, frozenset({normalised})))


def _declined_for_unread_imports(ev: Evidence, cid: str) -> Result | None:
    """Decline an import control when the collector observed nothing to go on.

    The README's own rule is that a control may return PASS only when a collector
    actually observed something, and both import controls broke it: a file that does
    not parse used to contribute an empty set, which is indistinguishable from a file
    that imports nothing, so a repository whose only Python file is broken came back
    [ok] on both.
    """
    if ev.python_files and not ev.imported_modules and ev.unreadable_files:
        return _result(
            cid,
            NOT_APPLICABLE,
            f"{len(ev.unreadable_files)} of {len(ev.python_files)} Python file(s) could "
            "not be read, and no import was collected from the rest",
            ev.pyproject_path,
        )
    return None


def _coverage_caveat(ev: Evidence) -> str:
    """What a PASS over a partially-read repository is worth.

    A clean verdict over 99 of 100 files is still a clean verdict, but it is not the
    same claim as one over 100 of 100, and the report has to say which it is.
    """
    if not ev.unreadable_files:
        return ""
    return (
        f" ({len(ev.unreadable_files)} of {len(ev.python_files)} Python file(s) "
        "could not be read)"
    )


def declared_deps_are_used(ev: Evidence) -> Result:
    """Every declared dependency should be imported somewhere.

    This is the check that found unused dependencies across the portfolio,
    and it is deliberately one-directional - see `imports_are_declared` for
    the other side, which is the more dangerous one.
    """
    cid = "deps-used"
    if ev.pyproject_path is None:
        return _result(cid, NOT_APPLICABLE, "no pyproject.toml")
    declined = _declined_for_unread_imports(ev, cid)
    if declined is not None:
        return declined

    declared = _declared_names(ev)
    if not declared:
        return _result(cid, PASS, "declares no dependencies", ev.pyproject_path)

    imported: set[str] = set()
    for module in ev.imported_modules:
        imported.add(module.lower().replace("-", "_"))
        imported |= _provides(module)
    unused = sorted(d for d in declared if d not in imported)
    if unused:
        return _result(
            cid, FAIL, f"declared but never imported: {', '.join(unused)}", ev.pyproject_path
        )
    return _result(
        cid,
        PASS,
        f"all {len(declared)} declared dependencies are imported{_coverage_caveat(ev)}",
        ev.pyproject_path,
    )


def imports_are_declared(ev: Evidence) -> Result:
    """Every third-party import should be declared.

    The more dangerous direction: an undeclared import works on the machine
    that has it installed and fails for everyone else.
    """
    cid = "imports-declared"
    if ev.pyproject_path is None:
        return _result(cid, NOT_APPLICABLE, "no pyproject.toml")

    declined = _declined_for_unread_imports(ev, cid)
    if declined is not None:
        return declined

    local = set(ev.local_packages) | {Path_stem(p) for p in ev.python_files}
    local |= {"src", "tests", "scripts", "ui", "shared", "projects", "conftest"}
    declared = _declared_names(ev)

    undeclared = sorted(
        m
        for m in ev.imported_modules
        if m not in _STDLIB_ISH and m not in local and not (_provides(m) & declared)
    )
    if undeclared:
        return _result(
            cid,
            FAIL,
            f"imported but not declared: {', '.join(undeclared[:8])}",
            ev.pyproject_path,
        )
    return _result(
        cid,
        PASS,
        f"every third-party import is declared{_coverage_caveat(ev)}",
        ev.pyproject_path,
    )


def Path_stem(rel: str) -> str:  # noqa: N802 - kept short, used once above
    return rel.split("/")[-1].removesuffix(".py")


# -- repository hygiene ---------------------------------------------------


def has_tests(ev: Evidence) -> Result:
    cid = "tests-exist"
    if not ev.python_files:
        return _result(cid, NOT_APPLICABLE, "no Python files")
    if not ev.test_files:
        return _result(cid, FAIL, f"{len(ev.source_files)} source files, no test files")
    ratio = len(ev.test_files) / max(1, len(ev.source_files))
    return _result(
        cid,
        PASS,
        f"{len(ev.test_files)} test files for {len(ev.source_files)} "
        f"source files ({ratio:.2f} ratio)",
    )


def has_licence(ev: Evidence) -> Result:
    return _result(
        "licence",
        PASS if ev.has_license else FAIL,
        "LICENSE present" if ev.has_license else "no LICENSE file",
    )


def is_backed_up(ev: Evidence) -> Result:
    """A folder of work with no remote is one disk failure from gone."""
    cid = "backed-up"
    if not ev.has_git:
        return _result(cid, FAIL, "not a git repository at all")
    if not ev.has_remote:
        return _result(cid, FAIL, "git repository with no remote - local only")
    return _result(cid, PASS, "has a remote")


def no_tracked_junk(ev: Evidence) -> Result:
    cid = "no-junk"
    if not ev.has_git:
        return _result(cid, NOT_APPLICABLE, "not a git repository")
    if ev.tracked_junk:
        return _result(
            cid,
            FAIL,
            f"{len(ev.tracked_junk)} junk file(s) tracked, e.g. {ev.tracked_junk[0]}",
        )
    return _result(cid, PASS, "no caches, venvs, logs or .env tracked")


CONTROLS: tuple[Control, ...] = (
    Control("readme-exists", "Every repository has a README of substance.", readme_exists),
    Control(
        "readme-limits", "Every README has a 'what it does NOT do' section.", readme_limits
    ),
    Control(
        "readme-problems",
        "Every README has 'problems hit while building this'.",
        readme_problems,
    ),
    Control("readme-io", "Every README states what goes in and what comes out.", readme_io),
    Control(
        "deps-used", "Every declared dependency is actually imported.", declared_deps_are_used
    ),
    Control("imports-declared", "Every third-party import is declared.", imports_are_declared),
    Control("tests-exist", "Every repository with source has tests.", has_tests),
    Control("licence", "Every repository has a LICENSE.", has_licence),
    Control("backed-up", "Every repository has a git remote.", is_backed_up),
    Control("no-junk", "No caches, venvs, logs or secrets are tracked.", no_tracked_junk),
)


def run_all(ev: Evidence) -> list[Result]:
    if not ev.exists:
        return [_result(c.id, INCONCLUSIVE, "directory does not exist") for c in CONTROLS]
    return [c.check(ev) for c in CONTROLS]
