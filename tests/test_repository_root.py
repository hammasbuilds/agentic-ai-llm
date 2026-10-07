"""Nothing is tracked at the repository root but the files that belong there.

A 0-byte file named `0.85` was committed and sat between `.gitignore` and `LICENSE` in
`git ls-files` for two commits. It came from a shell redirect in a command that was
editing an assertion reading `0.85 < measured`, and 2,354 tests did not notice a stray
file at the front door - which is the same blind spot `test_documented_counts.py`
describes at the root suite's own published count.

An allowlist rather than a pattern, because the thing that got in was a plausible
filename. A new file at the root is a deliberate act and adding it here is one line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Everything tracked directly at the root. Directories are listed by their first
#: path component, which is how `git ls-files` reports their contents.
ALLOWED_FILES = {
    ".gitignore",
    "LICENSE",
    "README.md",
    "RUNNING.md",
    "docker-compose.yml",
    "pyproject.toml",
    "serve_all.sh",
    # `run_tests.bat` is deliberately absent: it exists on disk and is NOT tracked,
    # which this list would have hidden by allowing it either way.
    "uv.lock",
    "worker.py",
}

#: Top-level directories that may hold tracked files.
ALLOWED_DIRECTORIES = {".github", "apps", "data", "products", "projects", "scripts", "tests"}


def _tracked() -> list[str]:
    done = subprocess.run(
        ["git", "ls-files"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def test_git_answers_at_all():
    """A sweep over an empty list passes, and this repository has thousands of files."""
    assert len(_tracked()) > 500, len(_tracked())


def test_nothing_unexpected_is_tracked_at_the_root():
    stray = sorted(path for path in _tracked() if "/" not in path and path not in ALLOWED_FILES)
    assert not stray, (
        f"tracked at the repository root and not in ALLOWED_FILES: {stray}. "
        "If one of these belongs there, add it to the list; `0.85` did not."
    )


def test_no_unexpected_top_level_directory_holds_tracked_files():
    stray = sorted(
        {
            path.split("/", 1)[0]
            for path in _tracked()
            if "/" in path and path.split("/", 1)[0] not in ALLOWED_DIRECTORIES
        }
    )
    assert not stray, f"tracked under an unlisted top-level directory: {stray}"


def test_the_file_that_got_in_is_gone():
    """Named, because a count alone is satisfied by widening the allowlist."""
    assert "0.85" not in _tracked()
    assert not (ROOT / "0.85").exists()


def test_every_allowed_root_file_is_actually_there():
    """An allowlist that has outlived its files stops being a check. A name removed
    from the repository should come off the list rather than sit on it forever."""
    tracked = set(_tracked())
    missing = sorted(name for name in ALLOWED_FILES if name not in tracked)
    assert not missing, f"allowed and not tracked: {missing}"
