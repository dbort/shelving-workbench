"""The FreeCAD-directory guard in ``tests/conftest.py``, in real pytest
processes.

``tests/test_collection.py`` covers the rule itself. What only a real run
shows is pytest's own behaviour around the hooks that apply it: that it
never asks ``pytest_ignore_collect`` about command-line paths, and that it
imports a named directory's ``conftest.py`` before collection starts. If a
pytest upgrade changed either, a mixed run would start FreeCAD again and
hang, so every run here has a timeout and uses ``--collect-only``, which
still runs each conftest's ``pytest_sessionstart``.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TIMEOUT_S = 120
_HEADLESS_NOTE = "skipped tests/freecad/:"
_GUI_NOTE = "skipped tests/freecad_gui/:"


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *args,
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )


def _settings_dirs() -> set[Path]:
    """The throwaway FreeCAD settings trees that exist right now
    (``tests/freecad_env.py`` makes them in the system temp directory)."""
    return set(Path(tempfile.gettempdir()).glob("shelving-freecad-*"))


def _freecad_node_ids(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.startswith(("tests/freecad/", "tests/freecad_gui/"))
    ]


@pytest.mark.parametrize(
    ("targets", "notes"),
    [
        ((), (_HEADLESS_NOTE, _GUI_NOTE)),
        (("tests",), (_HEADLESS_NOTE, _GUI_NOTE)),
        (
            ("tests/freecad", "tests/freecad_gui", "tests/test_collection.py"),
            (_HEADLESS_NOTE, _GUI_NOTE),
        ),
        (("tests/freecad_gui/test_panel.py", "tests/test_collection.py"), (_GUI_NOTE,)),
    ],
)
def test_a_mixed_run_collects_no_freecad_test_and_says_so(
    targets: tuple[str, ...], notes: tuple[str, ...]
) -> None:
    before = _settings_dirs()
    result = _collect(*targets)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert _freecad_node_ids(output) == []
    for note in (_HEADLESS_NOTE, _GUI_NOTE):
        assert (note in output) == (note in notes), output
    # No FreeCAD started, so no settings tree was made.
    assert _settings_dirs() == before


def test_ignored_directories_are_left_out_without_a_note() -> None:
    result = _collect("tests", "--ignore=tests/freecad", "--ignore=tests/freecad_gui")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert _freecad_node_ids(output) == []
    assert _HEADLESS_NOTE not in output
    assert _GUI_NOTE not in output


def test_a_run_aimed_at_the_headless_directory_collects_it() -> None:
    before = _settings_dirs()
    result = _collect("tests/freecad")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert len(_freecad_node_ids(output)) >= 47
    assert _HEADLESS_NOTE not in output
    assert _settings_dirs() == before
