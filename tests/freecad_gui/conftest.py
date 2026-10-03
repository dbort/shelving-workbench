"""FreeCAD's GUI, started offscreen for the tests in this directory, against
throwaway settings whose notification popups are off
(``.claude/docs/freecad-notes.md``: a popup deadlocks FreeCAD 1.1 when
offscreen).

The GUI starts in :func:`pytest_sessionstart`, not when this module is
imported: pytest imports the conftest of every directory named on its
command line before any collection decision, and a run that also names
other tests must not start FreeCAD here (:mod:`tests.collection`).
"""

import os
from pathlib import Path
from typing import cast

import pytest
from PySide6 import QtWidgets

from tests.collection import runs_only_inside
from tests.freecad_env import (
    isolate_freecad_settings,
    load_freecad,
    remove_settings,
)

_HERE = Path(__file__).resolve().parent
_SETTINGS = pytest.StashKey[Path]()
# The QApplication, held for the whole session: the GUI needs it alive.
_APP = pytest.StashKey[QtWidgets.QApplication]()


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if not runs_only_inside(_HERE, config.args, config.invocation_params.dir):
        return
    # A plain assignment, not setdefault: a developer's shell may export
    # another platform (wayland, xcb), and these tests must never open a
    # real window.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # Before FreeCAD loads: it reads its settings location only at startup.
    config.stash[_SETTINGS] = isolate_freecad_settings()
    load_freecad()
    import FreeCADGui

    config.stash[_APP] = cast(
        "QtWidgets.QApplication | None", QtWidgets.QApplication.instance()
    ) or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    root = session.config.stash.get(_SETTINGS, None)
    if root is not None:
        remove_settings(root)
