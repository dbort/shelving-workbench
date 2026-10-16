"""FreeCAD's GUI on a real X display, for tests that need its 3D view.

Offscreen Qt cannot create FreeCAD's 3D view, so this directory runs under
the Xvfb display ``tools/xvfb_run.py`` provides; a run started without one
stops before FreeCAD loads. The GUI starts in :func:`pytest_sessionstart`
for the reason ``tests/freecad_gui/conftest.py`` gives.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from PySide6 import QtWidgets

from tests.collection import runs_only_inside
from tests.freecad_env import isolate_freecad_settings, load_freecad, remove_settings

if TYPE_CHECKING:
    # Imports FreeCAD, which only pytest_sessionstart may load.
    import FreeCAD

    from tests.freecad_view.view import ViewDriver

_HERE = Path(__file__).resolve().parent
_SETTINGS = pytest.StashKey[Path]()
# The QApplication, held for the whole session: the GUI needs it alive.
_APP = pytest.StashKey[QtWidgets.QApplication]()

_USAGE = (
    "tests/freecad_view/ needs an X display: run it as "
    "`pixi run python -m tools.xvfb_run pytest tests/freecad_view`"
)


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if not runs_only_inside(_HERE, config.args, config.invocation_params.dir):
        return
    if not os.environ.get("DISPLAY") or os.environ.get("QT_QPA_PLATFORM") != "xcb":
        pytest.exit(_USAGE, returncode=2)
    # Before FreeCAD loads: it reads its settings location only at startup.
    config.stash[_SETTINGS] = isolate_freecad_settings()
    load_freecad()
    import FreeCADGui

    config.stash[_APP] = cast(
        "QtWidgets.QApplication | None", QtWidgets.QApplication.instance()
    ) or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    main_window.resize(1400, 900)
    main_window.show()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    root = session.config.stash.get(_SETTINGS, None)
    if root is not None:
        remove_settings(root)


@pytest.fixture
def unit(driver: "ViewDriver") -> Iterator["FreeCAD.DocumentObject"]:
    """A fresh unit in the driver's document, made in one step of its own,
    with the workbench active as a toolbar click needs. A task dialog still
    open at the end is closed."""
    import FreeCAD
    import FreeCADGui

    from freecad.Shelving.unit_ops import create_unit

    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    doc.UndoMode = 1
    doc.openTransaction("Create Shelving Unit")
    container = create_unit(doc)
    doc.commitTransaction()
    doc.recompute()
    driver.pump()
    yield container
    if FreeCADGui.Control.activeDialog():
        FreeCADGui.Control.closeDialog()
        driver.pump()


@pytest.fixture
def driver() -> Iterator["ViewDriver"]:
    """A new document shown in an active 3D view, and a driver for that
    view. Every document open when the test ends is closed."""
    import FreeCAD
    import FreeCADGui

    from tests.freecad_view.view import ViewDriver

    FreeCAD.newDocument("ViewTest")
    driver = ViewDriver.for_active_view()
    yield driver
    FreeCADGui.Selection.clearSelection()
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    driver.pump()
