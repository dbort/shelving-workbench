"""The setup actions and advisory checks the case files name.

Each one works on FreeCAD's active document through the workbench's public
API, so it is no more than a person would do by hand. FreeCAD is imported
inside each function: importing this module to read the registry must not
start FreeCAD.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol, cast

from freecad.Shelving.qa.registry import CheckResult, action, check

if TYPE_CHECKING:
    import FreeCAD

    from freecad.Shelving.core.layout import Region

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


def _new_document(name: str) -> FreeCAD.Document:
    """A new document with undo on, as one made with File, New has; a
    scripted document starts with it off. With the GUI up, any open task
    dialog is first rejected, as its Close button would."""
    import FreeCAD

    if FreeCAD.GuiUp:
        import FreeCADGui

        # A panel the last case left open would refuse the new case's Edit
        # Unit; closing it as its Close button does lets it clean up.
        dialog = FreeCADGui.Control.activeTaskDialog()
        if dialog is not None:
            dialog.reject()
    doc = FreeCAD.newDocument(name)
    doc.UndoMode = 1
    return doc


@contextmanager
def _undo_step(doc: FreeCAD.Document, name: str) -> Generator[None]:
    """One undo step named ``name`` around a setup, as a person's own edit
    would be."""
    doc.openTransaction(name)
    try:
        yield
    except BaseException:
        doc.abortTransaction()
        raise
    doc.commitTransaction()


def _object(name: str) -> FreeCAD.DocumentObject:
    obj = _active_document().getObject(name)
    if obj is None:
        raise RuntimeError(f"the active document has no '{name}'")
    return cast("FreeCAD.DocumentObject", obj)


def _add_box(
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
) -> None:
    import FreeCAD

    doc = _active_document()
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(FreeCAD.Vector(*corner_mm), FreeCAD.Rotation())
    container = cast("FreeCAD.DocumentObjectGroup", _object(_TEST_UNIT))
    container.addObject(cast("FreeCAD.DocumentObject", box))
    doc.recompute()


@action("test_unit", label="Create TestUnit, a five-box unit")
def test_unit() -> None:
    doc = _new_document("QA_Scan")
    with _undo_step(doc, "Create TestUnit"):
        doc.addObject("App::Part", _TEST_UNIT)
        _add_box("Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
        _add_box("Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
        _add_box("LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
        _add_box("RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
        _add_box("Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))


@action("add_overlap_box", label="Add a box overlapping LeftSide")
def add_overlap_box() -> None:
    with _undo_step(_active_document(), "Add Overlap"):
        _add_box("Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))


@action("fresh_unit", label="Create a fresh unit in a new document")
def fresh_unit() -> None:
    from freecad.Shelving.unit_ops import create_unit

    doc = _new_document("QA_Unit")
    with _undo_step(doc, "Create Shelving Unit"):
        create_unit(doc)
        doc.recompute()


def _bay_ids(region: Region) -> list[str]:
    from freecad.Shelving.core.layout import Bay, Board, Division

    if isinstance(region, Bay):
        return [region.id]
    if not isinstance(region, Division):
        return []
    return [
        found
        for item in region.items
        if not isinstance(item, Board)
        for found in _bay_ids(item)
    ]


@action("shelf_unit_with_varset", label="Create a shelf unit and VarSet.Len = 300 mm")
def shelf_unit_with_varset() -> None:
    from freecad.Shelving.editor.session import Session

    fresh_unit()
    doc = _active_document()
    with _undo_step(doc, "Add VarSet"):
        varset = doc.addObject("App::VarSet", "VarSet")
        varset.addProperty("App::PropertyLength", "Len")
        cast("_VarSet", varset).Len = "300 mm"

    session = Session(_object(_FRESH_UNIT))
    session.open()
    session.select(_bay_ids(session.unit.root)[0])
    failure = session.split("vertical")
    session.close()
    if failure is not None:
        raise RuntimeError(failure.message)
    doc.recompute()


@action("large_unit", label="Create a unit of four columns of six openings")
def large_unit() -> None:
    from freecad.Shelving.core.geometry import Space
    from freecad.Shelving.editor.session import Session, SplitDirection

    fresh_unit()
    doc = _active_document()
    with _undo_step(doc, "Divide Unit"):
        # Never opened, so its splits land in this one step.
        session = Session(_object(_FRESH_UNIT))

        def split_largest(direction: SplitDirection, column_x_mm: float | None) -> None:
            def extent_mm(space: Space) -> float:
                return space.size.x_mm if direction == "horizontal" else space.size.z_mm

            bays = [
                (region_id, session.spaces[region_id])
                for region_id in _bay_ids(session.unit.root)
                if column_x_mm is None
                or session.spaces[region_id].origin.x_mm == column_x_mm
            ]
            region_id, _space = max(bays, key=lambda bay: extent_mm(bay[1]))
            session.select(region_id)
            failure = session.split(direction)
            if failure is not None:
                raise RuntimeError(failure.message)

        for _ in range(3):
            split_largest("horizontal", None)
        columns_mm = sorted(
            {session.spaces[bay].origin.x_mm for bay in _bay_ids(session.unit.root)}
        )
        for column_x_mm in columns_mm:
            for _ in range(5):
                split_largest("vertical", column_x_mm)
        doc.recompute()


@check("fresh_unit_size")
def fresh_unit_size(doc: FreeCAD.Document | None) -> CheckResult:
    from freecad.Shelving.unit_ops import unit_size_mm

    container = None if doc is None else doc.getObject(_FRESH_UNIT)
    if container is None:
        return CheckResult(passed=False, detail=f"no {_FRESH_UNIT} found")
    size = unit_size_mm(container)
    sizes_mm = (size.x_mm, size.y_mm, size.z_mm)
    expected_mm = (600.0, 300.0, 900.0)
    passed = all(
        abs(actual_mm - want_mm) < 1e-6
        for actual_mm, want_mm in zip(sizes_mm, expected_mm, strict=True)
    )
    detail = " x ".join(f"{value_mm:g}" for value_mm in sizes_mm) + " mm"
    return CheckResult(passed=passed, detail=detail)
