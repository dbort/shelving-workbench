"""A document this workbench wrote opens in a FreeCAD that does not have it:
every board is there, where it was, and FreeCAD reports nothing amiss."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import FreeCAD

from freecad.Shelving.unit_ops import create_unit
from tests.freecad_view import open_without_workbench
from tests.freecad_view.open_without_workbench import Result
from tests.freecad_view.view import ViewDriver

_REPO = Path(__file__).resolve().parents[2]
_TIMEOUT_S = 120
# What FreeCAD writes to the Report view or the console when a document
# needs something it cannot load.
_TROUBLE = ("Error", "Traceback", "No module named", "Exception")


def _bounds_mm(doc: FreeCAD.Document) -> dict[str, list[float]]:
    found_mm: dict[str, list[float]] = {}
    for obj in doc.Objects:
        if obj.TypeId == "Part::Box":
            box = cast("open_without_workbench._Shaped", obj).Shape.BoundBox
            found_mm[obj.Name] = [
                box.XMin,
                box.YMin,
                box.ZMin,
                box.XMax,
                box.YMax,
                box.ZMax,
            ]
    return found_mm


def test_a_saved_unit_opens_without_the_workbench(
    driver: ViewDriver, tmp_path: Path
) -> None:
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    create_unit(doc)
    doc.recompute()
    path = tmp_path / "unit.FCStd"
    doc.saveAs(str(path))
    saved_bounds_mm = _bounds_mm(doc)
    assert len(saved_bounds_mm) == 4

    result_path = tmp_path / "result.json"
    child = subprocess.run(
        [
            sys.executable,
            open_without_workbench.__file__,
            str(path),
            str(_REPO),
            str(result_path),
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    output = child.stdout + child.stderr
    assert child.returncode == 0, output
    result = cast("Result", json.loads(result_path.read_text(encoding="utf-8")))

    assert "ShelvingWorkbench" not in result["workbenches"], result["workbenches"]
    opened_bounds_mm = {board["name"]: board["bounds_mm"] for board in result["boards"]}
    assert opened_bounds_mm.keys() == saved_bounds_mm.keys()
    for name, bounds_mm in saved_bounds_mm.items():
        assert all(
            abs(opened_mm - saved_mm) < 1e-6
            for opened_mm, saved_mm in zip(
                opened_bounds_mm[name], bounds_mm, strict=True
            )
        ), (name, opened_bounds_mm[name], bounds_mm)
    trouble = [
        row
        for row in (result["report"] + "\n" + output).splitlines()
        if any(word in row for word in _TROUBLE)
    ]
    assert trouble == [], trouble
