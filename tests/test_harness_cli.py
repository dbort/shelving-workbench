"""Fast-tier coverage of ``test.sh``'s CLI and exit-status contract.

``test.sh`` is the task pipeline's test harness and agents branch on its exit
codes: 2 for a usage error, 3 for a failed tool preflight, 1 (with an exact
message) when ``freecadcmd`` is absent, and any other non-zero status straight
from the underlying lint/type/test tool. Those behaviors are load-bearing, so
they get real coverage here instead of being re-derived by hand each review
round.

RECURSION SAFETY: ``test.sh``'s fast sequence runs ``pytest shelving_core
tests``, which re-enters this file. Every subprocess call below therefore
either passes arguments that fail ``test.sh``'s usage check (exit 2, reached
before any tool runs) or runs it under a stripped ``PATH`` that makes the
preflight abort (exit 3) before the fast sequence starts. Nothing here invokes
``./test.sh --fast`` or ``--full`` with a ``PATH`` that could let the harness
reach ``pytest``. The ``freecadcmd``-absent branch, which needs a live
non-FreeCAD environment to execute, is checked by scanning ``test.sh``'s
source, the same technique as ``shelving_core/tests/test_no_freecad.py``.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_SH = REPO_ROOT / "test.sh"

USAGE_LINE = "usage: test.sh --fast | --full"

FAST_TOOLS = ("python3", "ruff", "mypy", "pytest", "rsync")
FULL_TOOLS = FAST_TOOLS + ("actionlint", "zizmor", "check-jsonschema", "shellcheck")

FREECAD_MISSING_MESSAGE = (
    "ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for "
    "the full test tier; see README.md."
)

_BASH = shutil.which("bash") or "bash"


def _run(args, env=None):
    return subprocess.run(
        [_BASH, str(TEST_SH), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def stripped_path_env(tmp_path):
    """Environment whose ``PATH`` holds only ``dirname`` (and ``pwd`` if external).

    That is enough for ``test.sh`` to resolve its own repo root at start-up,
    but every tool the preflight looks for is absent, so the preflight always
    fails with exit 3 before the fast sequence (which would re-enter pytest)
    can run.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dirname = shutil.which("dirname")
    assert dirname, "dirname not found on PATH; test environment too minimal"
    os.symlink(dirname, bin_dir / "dirname")
    pwd = shutil.which("pwd")
    if pwd:
        os.symlink(pwd, bin_dir / "pwd")
    return {"PATH": str(bin_dir)}


@pytest.mark.parametrize("args", [[], ["--bogus"], ["--fast", "--full"]])
def test_usage_errors_exit_2(args):
    # These fail test.sh's argument check before the preflight or the fast
    # sequence runs, so a full inherited PATH here cannot cause recursion.
    result = _run(args)
    assert result.returncode == 2
    assert USAGE_LINE in result.stderr


def test_fast_preflight_names_missing_tools(stripped_path_env):
    result = _run(["--fast"], env=stripped_path_env)
    assert result.returncode == 3
    for tool in FAST_TOOLS:
        assert tool in result.stderr
    assert "tools/install-deps.sh" in result.stderr
    assert "pixi shell" in result.stderr


def test_full_preflight_names_missing_tools(stripped_path_env):
    result = _run(["--full"], env=stripped_path_env)
    assert result.returncode == 3
    for tool in FULL_TOOLS:
        assert tool in result.stderr
    assert "tools/install-deps.sh" in result.stderr
    assert "pixi shell" in result.stderr


def test_source_has_exact_freecadcmd_missing_message_then_exit_1():
    # Source scan, not execution: reaching this branch needs a live env with no
    # FreeCAD, and running test.sh far enough to hit it would re-enter pytest.
    lines = TEST_SH.read_text(encoding="utf-8").splitlines()
    idx = next(
        (i for i, line in enumerate(lines) if FREECAD_MISSING_MESSAGE in line), None
    )
    assert idx is not None, f"exact freecadcmd-missing message not found in {TEST_SH}"
    assert any("exit 1" in line for line in lines[idx : idx + 5]), (
        "expected `exit 1` within a few lines of the freecadcmd-missing message"
    )
