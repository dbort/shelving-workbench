"""FreeCAD's GUI, started offscreen for the tests in this directory, against
throwaway settings whose notification popups are off, with a Qt message
handler that drops offscreen Qt's unsupported-plugin warnings.

Popups off does not keep every popup away: FreeCAD 1.1.3 shows one for a
message identical to the previous one while its main window is active.
Offscreen, that popup's ``raise()`` warns, and FreeCAD's own handler turns
the warning into a notification while the Notification Area holds its
lock, which deadlocks the suite. The replacement handler
(:mod:`tests.qt_messages`) drops that warning family and forwards the rest
to FreeCAD's console (``.claude/docs/freecad-notes.md`` § A headless
notification popup deadlocks FreeCAD 1.1).

The GUI starts in :func:`pytest_sessionstart`, not when this module is
imported: pytest imports the conftest of every directory named on its
command line before any collection decision, and a run that also names
other tests must not start FreeCAD here (:mod:`tests.collection`).
"""

import os
from pathlib import Path
from typing import cast

import pytest
from PySide6 import QtCore, QtWidgets

from tests.collection import runs_only_inside
from tests.freecad_env import (
    isolate_freecad_settings,
    load_freecad,
    remove_settings,
)
from tests.qt_messages import message_handler

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
    import FreeCAD
    import FreeCADGui

    config.stash[_APP] = cast(
        "QtWidgets.QApplication | None", QtWidgets.QApplication.instance()
    ) or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()
    # FreeCAD installs its C++ handler while it initializes, before this
    # point. PySide6 cannot chain to it, so ours replaces it outright.
    QtCore.qInstallMessageHandler(message_handler(FreeCAD.Console))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    root = session.config.stash.get(_SETTINGS, None)
    if root is not None:
        remove_settings(root)
