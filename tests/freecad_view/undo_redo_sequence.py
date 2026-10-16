"""Runs, in a FreeCAD GUI of its own, the Undo and Redo sequence that
crashes plain FreeCAD's Gui Redo, inside an Edit Unit session, then writes
``done`` to the file named on the command line.

Run as ``python -m tests.freecad_view.undo_redo_sequence RESULT_FILE`` by
``test_undo_in_the_editor.py`` from the repository root, so a crash takes
down this process and not the test run. The caller provides the display,
the throwaway settings and glibc's allocator settings through the
environment. The result goes to a file because FreeCAD's GUI takes over
Python's standard output for its Report view.
"""

import os
import sys
from pathlib import Path


def main(result: Path) -> None:
    from tests.freecad_env import load_freecad

    load_freecad()
    import FreeCAD
    import FreeCADGui
    from PySide6 import QtWidgets

    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()
    # Only once FreeCAD's GUI has set up Coin: the editor imports pivy,
    # whose import before that left the first 3D view's render reading
    # freed memory.
    from freecad.Shelving.unit_ops import create_unit
    from tests.freecad_view.editor import (
        add_board,
        edit_unit,
        gui_step,
        press_delete,
    )
    from tests.freecad_view.view import ViewDriver

    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.newDocument("UndoRedoSequence")
    driver = ViewDriver.for_active_view()
    container = create_unit(doc)
    doc.recompute()
    panel = edit_unit(container, driver)

    # A freed read crashes only when the freed memory has been reused, so
    # the sequence runs several times.
    for _ in range(8):
        add_board(panel, "vertical", driver)
        press_delete(driver)
        gui_step("Std_Undo", driver)
        gui_step("Std_Undo", driver)
        add_board(panel, "horizontal", driver)
        gui_step("Std_Undo", driver)
        gui_step("Std_Redo", driver)
    panel.reject()
    FreeCADGui.Control.closeDialog()
    driver.pump(200)
    result.write_text("done", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
    sys.stdout.flush()
    # FreeCAD's GUI teardown can hang a scripted run.
    os._exit(0)
