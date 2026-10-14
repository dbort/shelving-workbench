"""Opens a saved document in FreeCAD's GUI with this workbench out of reach,
and writes what it found to a JSON file.

Run as a script, ``python open_without_workbench.py DOCUMENT REPO_ROOT
RESULT_FILE``,
by ``test_open_without_workbench.py``, never imported by the tests: FreeCAD
loads every ``freecad.*`` package it can import as a workbench, and the
editable install puts the repository on ``sys.path``, so the repository has
to leave ``sys.path`` before ``freecad`` is first imported. The caller
provides the display and the throwaway settings through the environment.
The result goes to a file because FreeCAD's GUI takes over Python's
standard output for its Report view.
"""

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Protocol, TypedDict, cast


class Board(TypedDict):
    name: str
    # XMin, YMin, ZMin, XMax, YMax, ZMax of the board's shape, in mm.
    bounds_mm: list[float]


class Result(TypedDict):
    workbenches: list[str]
    boards: list[Board]
    report: str


class _Shaped(Protocol):
    Name: str
    TypeId: str
    Shape: "_Shape"


class _Shape(Protocol):
    BoundBox: "_BoundBox"


class _BoundBox(Protocol):
    XMin: float
    YMin: float
    ZMin: float
    XMax: float
    YMax: float
    ZMax: float


def _outside(repo: Path) -> list[str]:
    """``sys.path`` without the repository's own entries: its root, which
    the editable install adds, and this script's folder. The pixi
    environment also lives under the root, so it is kept."""
    ours = (repo / "freecad", repo / "tests")
    kept: list[str] = []
    for entry in sys.path:
        resolved = Path(entry or os.getcwd()).resolve()
        if resolved == repo or any(resolved.is_relative_to(own) for own in ours):
            continue
        kept.append(entry)
    return kept


def main(document: Path, repo: Path) -> Result:
    sys.path[:] = _outside(repo.resolve())
    # Loads FreeCAD's libraries, so it must come before FreeCAD's modules.
    importlib.import_module("freecad")
    import FreeCAD
    import FreeCADGui
    from PySide6 import QtWidgets

    app = cast("QtWidgets.QApplication | None", QtWidgets.QApplication.instance())
    app = app or QtWidgets.QApplication([])
    FreeCADGui.showMainWindow()
    doc = FreeCAD.openDocument(str(document))
    end_s = time.monotonic() + 1.0
    while time.monotonic() < end_s:
        app.processEvents()
        time.sleep(0.01)
    boards: list[Board] = []
    for obj in cast("list[_Shaped]", doc.Objects):
        if obj.TypeId != "Part::Box":
            continue
        box = obj.Shape.BoundBox
        bounds_mm = [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]
        boards.append({"name": obj.Name, "bounds_mm": bounds_mm})
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    report = main_window.findChild(QtWidgets.QTextEdit, "Report view")
    return {
        "workbenches": sorted(FreeCADGui.listWorkbenches()),
        "boards": sorted(boards, key=lambda board: board["name"]),
        "report": report.toPlainText() if report is not None else "",
    }


if __name__ == "__main__":
    result = main(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result), encoding="utf-8")
    # FreeCAD's GUI teardown can hang a scripted run.
    os._exit(0)
