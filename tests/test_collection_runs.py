"""The FreeCAD-directory guard in ``tests/conftest.py``, in real pytest
processes.

``tests/test_collection.py`` covers the rule itself. What only a real run
shows is pytest's own behaviour around the hooks that apply it: that it
never asks ``pytest_ignore_collect`` about command-line paths, and that it
imports a named directory's ``conftest.py`` before collection starts. If a
pytest upgrade changed either, a mixed run would start FreeCAD again and
hang, so every run here has a timeout and uses ``--collect-only``, which
still runs each conftest's ``pytest_sessionstart``. Each run reports, after
pytest returns, the state a FreeCAD start leaves behind: ``XDG_CONFIG_HOME``
pointing at a throwaway settings tree (both directories' startups set it),
and ``FreeCADGui`` loaded, which in a mixed run only the GUI startup does.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TIMEOUT_S = 120
_HEADLESS_NOTE = "skipped tests/freecad/:"
_GUI_NOTE = "skipped tests/freecad_gui/:"
_STATE_PREFIX = "RUN STATE "

# Runs pytest in the child process, then prints what FreeCAD's startup would
# have changed in that process.
_DRIVER = f"""
import json, os, sys
import pytest
code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", *sys.argv[1:]])
print({_STATE_PREFIX!r} + json.dumps({{
    "xdg_config_home": os.environ.get("XDG_CONFIG_HOME", ""),
    "freecadgui_loaded": "FreeCADGui" in sys.modules,
}}))
sys.exit(int(code))
"""


@dataclass(frozen=True)
class _Run:
    returncode: int
    output: str
    # Whether either FreeCAD directory's startup ran: it points
    # XDG_CONFIG_HOME at a fresh tree under the run's own temp directory.
    settings_isolated: bool
    freecadgui_loaded: bool
    # Settings trees still in the run's temp directory afterwards.
    leftover_settings: list[Path]


def _collect(tmp_path: Path, *args: str) -> _Run:
    """Collect ``args`` in a child pytest with ``tmp_path`` as its temp
    directory, so its settings trees cannot mix with any other run's."""
    env = dict(os.environ, TMPDIR=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", _DRIVER, *args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    output = result.stdout + result.stderr
    (state_line,) = [
        line for line in result.stdout.splitlines() if line.startswith(_STATE_PREFIX)
    ]
    state = json.loads(state_line.removeprefix(_STATE_PREFIX))
    xdg_config_home = str(state["xdg_config_home"])
    return _Run(
        returncode=result.returncode,
        output=output,
        settings_isolated=xdg_config_home.startswith(str(tmp_path)),
        freecadgui_loaded=bool(state["freecadgui_loaded"]),
        leftover_settings=sorted(tmp_path.glob("shelving-freecad-*")),
    )


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
def test_a_mixed_run_starts_no_freecad_and_says_so(
    tmp_path: Path, targets: tuple[str, ...], notes: tuple[str, ...]
) -> None:
    run = _collect(tmp_path, *targets)
    assert run.returncode == 0, run.output
    assert _freecad_node_ids(run.output) == []
    for note in (_HEADLESS_NOTE, _GUI_NOTE):
        assert (note in run.output) == (note in notes), run.output
    assert not run.settings_isolated, run.output
    assert not run.freecadgui_loaded, run.output
    assert run.leftover_settings == []


def test_ignored_directories_are_left_out_without_a_note(tmp_path: Path) -> None:
    run = _collect(
        tmp_path, "tests", "--ignore=tests/freecad", "--ignore=tests/freecad_gui"
    )
    assert run.returncode == 0, run.output
    assert _freecad_node_ids(run.output) == []
    assert _HEADLESS_NOTE not in run.output
    assert _GUI_NOTE not in run.output
    assert not run.settings_isolated


def test_a_run_aimed_at_the_headless_directory_starts_freecad_there(
    tmp_path: Path,
) -> None:
    run = _collect(tmp_path, "tests/freecad")
    assert run.returncode == 0, run.output
    assert len(_freecad_node_ids(run.output)) >= 47
    assert _HEADLESS_NOTE not in run.output
    # FreeCADGui is loaded here too, as the headless stub the workbench's own
    # modules import, so it says nothing about which startup ran.
    assert run.settings_isolated
    assert run.leftover_settings == []
