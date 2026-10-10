"""The setup actions and advisory checks the case files name.

Each one works on FreeCAD's active document through the workbench's public
API, so it is no more than a person would do by hand. FreeCAD is imported
inside each function: importing this module to read the registry must not
start FreeCAD.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from freecad.Shelving.qa.registry import CheckResult, action, check

if TYPE_CHECKING:
    import FreeCAD

_TEST_UNIT = "TestUnit"
_FRESH_UNIT = "ShelvingUnit"


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


class _VarSet(Protocol):
    Len: str


def _active_document() -> FreeCAD.Document:
    import FreeCAD

    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("no document is open: run the case's first step")
    return doc


def _object(name: str) -> FreeCAD.DocumentObject:
    obj = _active_document().getObject(name)
    if obj is None:
        raise RuntimeError(f"the active document has no '{name}'")
    return cast("FreeCAD.DocumentObject", obj)


def _add_box(
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
    angle_deg: float = 0.0,
) -> None:
    import FreeCAD

    doc = _active_document()
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm),
        FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle_deg),
    )
    container = cast("FreeCAD.DocumentObjectGroup", _object(_TEST_UNIT))
    container.addObject(cast("FreeCAD.DocumentObject", box))
    doc.recompute()


@action("test_unit", label="Create TestUnit, a five-box unit")
def test_unit() -> None:
    import FreeCAD

    doc = FreeCAD.newDocument("QA_Scan")
    doc.addObject("App::Part", _TEST_UNIT)
    _add_box("Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
    _add_box("Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
    _add_box("LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
    _add_box("RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
    _add_box("Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))


@action("add_skewed_box", label="Add a box turned 30 degrees")
def add_skewed_box() -> None:
    _add_box("Skewed", (100.0, 50.0, 20.0), (0.0, 400.0, 0.0), angle_deg=30.0)


@action("add_overlap_box", label="Add a box overlapping LeftSide")
def add_overlap_box() -> None:
    _add_box("Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))


@action("save_to_temp", label="Save the document to a temporary folder")
def save_to_temp() -> str:
    doc = _active_document()
    path = Path(tempfile.mkdtemp(prefix="shelving-qa-")) / f"{doc.Name}.FCStd"
    doc.saveAs(str(path))
    return f"Saved to {path}"


@action("fresh_unit", label="Create a fresh unit in a new document")
def fresh_unit() -> None:
    import FreeCAD

    from freecad.Shelving.unit_ops import create_unit

    doc = FreeCAD.newDocument("QA_Unit")
    create_unit(doc)
    doc.recompute()


@action("nudge_side_1", label="Move Side 1 2 mm toward the center")
def nudge_side_1() -> None:
    side = cast("_BoxFeature", _object("left_side"))
    placement = side.Placement
    placement.Base.x = 2.0
    side.Placement = placement
    _active_document().recompute()


@action("shelf_unit_with_varset", label="Create a shelf unit and VarSet.Len = 300 mm")
def shelf_unit_with_varset() -> None:
    from freecad.Shelving.core.layout import Bay, Division, Region
    from freecad.Shelving.editor.session import Session

    fresh_unit()
    doc = _active_document()
    varset = doc.addObject("App::VarSet", "VarSet")
    varset.addProperty("App::PropertyLength", "Len")
    cast("_VarSet", varset).Len = "300 mm"

    def first_bay(region: Region) -> str | None:
        if isinstance(region, Bay):
            return region.id
        if isinstance(region, Division):
            for item in region.items:
                if isinstance(item, Bay | Division):
                    found = first_bay(item)
                    if found is not None:
                        return found
        return None

    session = Session(_object(_FRESH_UNIT))
    session.open()
    session.select(first_bay(session.unit.root))
    failure = session.split("vertical")
    if failure is not None:
        session.cancel()
        raise RuntimeError(failure.message)
    session.commit()
    doc.recompute()


@action("add_untagged_cube", label="Add a 400 x 5 x 400 mm cube to the unit")
def add_untagged_cube() -> None:
    doc = _active_document()
    cube = cast("_BoxFeature", doc.addObject("Part::Box", "Cube"))
    cube.Length, cube.Width, cube.Height = 400.0, 5.0, 400.0
    container = cast("FreeCAD.DocumentObjectGroup", _object(_FRESH_UNIT))
    container.addObject(cast("FreeCAD.DocumentObject", cube))
    doc.recompute()


@check("side_1_at_x_zero")
def side_1_at_x_zero(doc: FreeCAD.Document | None) -> CheckResult:
    side = None if doc is None else doc.getObject("left_side")
    if side is None:
        return CheckResult(passed=False, detail="no Side 1 (left_side) found")
    x_mm = float(cast("_BoxFeature", side).Placement.Base.x)
    return CheckResult(passed=abs(x_mm) < 1e-6, detail=f"Side 1 x = {x_mm:g} mm")


@check("boxes_json_beside_document")
def boxes_json_beside_document(doc: FreeCAD.Document | None) -> CheckResult:
    if doc is None or not doc.FileName:
        return CheckResult(passed=False, detail="the document is not saved")
    path = Path(doc.FileName).parent / f"{_TEST_UNIT}.boxes.json"
    return CheckResult(passed=path.is_file(), detail=f"looked for {path}")


@check("fresh_unit_size")
def fresh_unit_size(doc: FreeCAD.Document | None) -> CheckResult:
    from freecad.Shelving.unit_ops import unit_size_mm

    container = None if doc is None else doc.getObject(_FRESH_UNIT)
    if container is None:
        return CheckResult(passed=False, detail=f"no {_FRESH_UNIT} found")
    size = unit_size_mm(container)
    sizes_mm = (size.x_mm, size.y_mm, size.z_mm)
    expected_mm = (600.0, 300.0, 900.0)
    passed = all(abs(a - b) < 1e-6 for a, b in zip(sizes_mm, expected_mm, strict=True))
    detail = " x ".join(f"{value_mm:g}" for value_mm in sizes_mm) + " mm"
    return CheckResult(passed=passed, detail=detail)


@check("four_boards")
def four_boards(doc: FreeCAD.Document | None) -> CheckResult:
    count = (
        0 if doc is None else sum(1 for obj in doc.Objects if obj.TypeId == "Part::Box")
    )
    return CheckResult(passed=count == 4, detail=f"{count} boxes in the document")
