"""The repo's pyrefly config keeps the gate as strict as ``CLAUDE.md`` § Typed
Python promises.

The config is checked by its effect, against a fixture that breaks each rule
once: a setting dropped or loosened in ``pyproject.toml`` leaves ``pixi run
tests`` green on the real tree, so only a planted violation shows it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# Each line breaks one rule; the comment names the error kind the repo's
# config must report there.
_FIXTURE = """\
from typing import cast


class Base:
    def method(self) -> None: ...


class Child(Base):
    def method(self) -> None: ...  # missing-override-decorator


def unannotated(value) -> None: ...  # implicit-any-parameter


hidden: int = "text"  {other_ignore}  # bad-assignment
stale: int = 1  # pyrefly: ignore[bad-assignment]  # unused-ignore
same = cast(int, stale)  # redundant-cast
again = int(stale)  # unnecessary-type-conversion
""".format(
    # Assembled so the repo itself carries no other checker's suppression.
    other_ignore="# type" + ": ignore"
)

_EXPECTED_MARK = re.compile(r"#\s*([a-z-]+)\s*$")
_REPORTED = re.compile(r"^ERROR tests/fixture\.py:(\d+):\S+ .*\[([a-z-]+)\]$", re.M)


def expected_errors(fixture: str) -> set[tuple[int, str]]:
    """The (line, error kind) pairs ``fixture``'s trailing comments name."""
    found: set[tuple[int, str]] = set()
    for number, line in enumerate(fixture.splitlines(), start=1):
        match = _EXPECTED_MARK.search(line)
        if match is not None:
            found.add((number, match.group(1)))
    return found


def test_the_fixture_marks_each_rule_once() -> None:
    assert {kind for _, kind in expected_errors(_FIXTURE)} == {
        "missing-override-decorator",
        "implicit-any-parameter",
        "bad-assignment",
        "unused-ignore",
        "redundant-cast",
        "unnecessary-type-conversion",
    }


def test_the_repo_config_reports_every_planted_violation(tmp_path: Path) -> None:
    """``bad-assignment`` under the generic ignore comment shows that only
    pyrefly's own suppressions are honored; the others show the preset and the raised
    severities are in force. Every one is an error, so the run fails."""
    pyrefly = shutil.which("pyrefly")
    if pyrefly is None:
        pytest.fail("pyrefly is not on PATH; run the checks with `pixi run tests`.")
    shutil.copy(PYPROJECT, tmp_path / "pyproject.toml")
    # Under one of the config's project-includes, so the config applies as
    # written.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text(_FIXTURE)
    run = subprocess.run(
        [pyrefly, "check", "--summary=none", "--output-format", "min-text"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    reported = {(int(line), kind) for line, kind in _REPORTED.findall(run.stdout)}
    assert reported == expected_errors(_FIXTURE), run.stdout + run.stderr
    assert run.returncode != 0
