"""FreeCAD's GUI, started offscreen for the tests in this directory, against
throwaway settings whose notification popups are off
(``.claude/docs/freecad-notes.md``: a popup deadlocks FreeCAD 1.1 when
offscreen)."""

import os
from typing import cast

import pytest

from tests.freecad_settings import isolate_freecad_settings, remove_settings

# A plain assignment, not setdefault: a developer's shell may export another
# platform (wayland, xcb), and these tests must never open a real window.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# Before FreeCAD loads: it reads its settings location only at startup.
_SETTINGS_ROOT = isolate_freecad_settings()

# The bootstrap above everything else FreeCAD: FreeCADGui is importable
# only once it has run.
import freecad  # noqa: E402, F401

# isort: split
import FreeCADGui  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

# Held for the whole session: the GUI needs its QApplication alive.
_APP = cast(
    "QtWidgets.QApplication | None", QtWidgets.QApplication.instance()
) or QtWidgets.QApplication([])
FreeCADGui.showMainWindow()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    remove_settings(_SETTINGS_ROOT)
