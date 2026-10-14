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

import gc
import os
import sys
from pathlib import Path


def main(result: Path) -> None:
    from tests.freecad_env import load_freecad

    load_freecad()
    import FreeCAD
    import FreeCADGui
    from PySide6 import QtWidgets

    from freecad.Shelving.core.layout import Bay, Board, Division, Region
    from freecad.Shelving.editor.panel import EditUnitPanel
    from freecad.Shelving.unit_ops import create_unit
    from tests.freecad_view.editor import gui_step
    from tests.freecad_view.view import ViewDriver

    def bays(region: Region) -> list[str]:
        if isinstance(region, Bay):
            return [region.id]
        if not isinstance(region, Division):
            return []
        return [
            b
            for item in region.items
            if not isinstance(item, Board)
            for b in bays(item)
        ]

    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.newDocument("UndoRedoSequence")
    driver = ViewDriver.for_active_view()
    container = create_unit(doc)
    doc.recompute()
    FreeCADGui.Selection.addSelection(container)
    FreeCADGui.runCommand("Shelving_EditUnit")
    driver.pump(300)
    (panel,) = [obj for obj in gc.get_objects() if isinstance(obj, EditUnitPanel)]
    session = panel.session
    session.select(bays(session.unit.root)[0])
    panel._refresh()
    panel.add_shelf_button.click()
    driver.pump(200)
    shelf = next(
        board_id
        for board_id in session.spaces
        if doc.getObject(board_id) is not None
        and board_id not in ("bottom", "top", "left_side", "right_side")
    )
    session.select(shelf)
    panel._refresh()
    panel.delete_button.click()
    driver.pump(200)
    gui_step("Std_Undo", driver)
    gui_step("Std_Undo", driver)
    session.select(bays(session.unit.root)[0])
    panel._refresh()
    panel.add_divider_button.click()
    driver.pump(200)
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
