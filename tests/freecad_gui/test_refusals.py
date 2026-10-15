"""Every command's refusal path, with FreeCAD's GUI up so the commands can
read and change the 3D view's selection.

Each command is driven through its ``Activated``, the method FreeCAD calls
when a user runs it.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtWidgets

from freecad.Shelving import refusals
from freecad.Shelving.commands import create_unit as create_unit_module
from freecad.Shelving.commands import edit_unit as edit_unit_module
from freecad.Shelving.commands.create_unit import CreateUnitCommand
from freecad.Shelving.commands.edit_unit import EditUnitCommand
from freecad.Shelving.commands.export_boxes import ExportBoxesCommand
from freecad.Shelving.container import write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Fixed,
    Region,
    SizeRule,
    Unit,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.init_gui import TOOLBAR_COMMANDS
from freecad.Shelving.unit_ops import create_unit


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


@dataclass(frozen=True)
class _Refusal:
    summary: str
    objects: tuple[str, ...]
    suggestion: str


@pytest.fixture
def doc() -> Iterator[FreeCAD.Document]:
    document = FreeCAD.newDocument("refusals")
    yield document
    FreeCADGui.Selection.clearSelection()
    FreeCAD.closeDocument(document.Name)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[_Refusal]:
    """Every refusal reported while the test runs, each still passed on to
    the real helper so its selection happens too."""
    calls: list[_Refusal] = []
    real = refusals.report_refusal

    def record(summary: str, objects: Iterable[str], suggestion: str) -> None:
        names = tuple(objects)
        calls.append(_Refusal(summary, names, suggestion))
        real(summary, names, suggestion)

    monkeypatch.setattr(refusals, "report_refusal", record)
    return calls


def _add_box(
    doc: FreeCAD.Document,
    container: FreeCAD.DocumentObject,
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
) -> None:
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(FreeCAD.Vector(*corner_mm), FreeCAD.Rotation())
    cast("FreeCAD.DocumentObjectGroup", container).addObject(
        cast("FreeCAD.DocumentObject", box)
    )


def _overlapping_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """A hand-built closed unit with a shelf, plus Overlap occupying exactly
    LeftSide's space: the QA wizard's TestUnit after its overlap step."""
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "TestUnit"))
    _add_box(doc, container, "Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
    _add_box(doc, container, "Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
    _add_box(doc, container, "LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
    _add_box(doc, container, "RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
    _add_box(doc, container, "Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))
    _add_box(doc, container, "Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
    doc.recompute()
    return container


def _board_snapshot(
    doc: FreeCAD.Document,
) -> list[tuple[str, float, float, float, FreeCAD.Placement]]:
    return [
        (obj.Name, box.Length, box.Width, box.Height, box.Placement)
        for obj in doc.Objects
        if obj.isDerivedFrom("Part::Box")
        for box in [cast("_BoxFeature", obj)]
    ]


def _selected_names() -> set[str]:
    selection = cast(
        "list[FreeCAD.DocumentObject]", FreeCADGui.Selection.getSelection()
    )
    return {obj.Name for obj in selection}


def test_edit_unit_refuses_overlapping_boards_and_selects_them(
    doc: FreeCAD.Document, recorded: list[_Refusal]
) -> None:
    """Edit Unit on a hand-built container that does not scan opens no
    panel and changes no board, reports the scanner's diagnosis with its
    suggestion, and selects the two boards the scanner named."""
    container = _overlapping_unit(doc)
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(container)
    before = _board_snapshot(doc)

    EditUnitCommand().Activated()

    assert recorded == [
        _Refusal(
            "Overlap overlaps LeftSide",
            ("Overlap", "LeftSide"),
            refusals.SUGGESTIONS["overlap"],
        )
    ]
    assert _selected_names() == {"Overlap", "LeftSide"}
    assert FreeCADGui.Control.activeDialog() is False
    assert _board_snapshot(doc) == before


def _fixed_shelf_unit() -> Unit:
    """A closed 600 x 300 x 900 mm unit whose one shelf sits between two
    openings of fixed height, 300 mm below and 546 mm above, which fill the
    864 mm between bottom and top exactly."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=18.0, role="left_side"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(rule=Fixed(size_mm=300.0)),
                                Board(thickness_mm=18.0, role="shelf"),
                                Bay(rule=Fixed(size_mm=546.0)),
                            ],
                        ),
                        Board(thickness_mm=18.0, role="right_side"),
                    ],
                ),
                Board(thickness_mm=18.0, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _bay_rules(region: Region) -> list[SizeRule]:
    if isinstance(region, Bay):
        return [region.rule]
    if not isinstance(region, Division):
        return []
    found: list[SizeRule] = []
    for item in region.items:
        if not isinstance(item, Board):
            found += _bay_rules(item)
    return found


def test_edit_unit_opens_locked_openings_at_the_size_hand_moves_left_them(
    doc: FreeCAD.Document,
) -> None:
    """Moving the top down and shortening the sides by hand leaves 100 mm
    less than the two locked openings stored: the boards win, so both stay
    locked and the upper one opens at the 446 mm left to it."""
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    write_container(container, _fixed_shelf_unit())
    doc.recompute()
    top = cast("_BoxFeature", doc.getObject("top"))
    top.Placement = FreeCAD.Placement(
        top.Placement.Base - FreeCAD.Vector(0.0, 0.0, 100.0), top.Placement.Rotation
    )
    for side in ("left_side", "right_side"):
        cast("_BoxFeature", doc.getObject(side)).Height = 764.0
    doc.recompute()
    before = _board_snapshot(doc)

    panel = panel_module.EditUnitPanel(container)
    try:
        rules = _bay_rules(panel.session.unit.root)
    finally:
        panel.reject()

    assert all(isinstance(rule, Fixed) for rule in rules), rules
    sizes_mm = sorted(rule.size_mm for rule in rules if isinstance(rule, Fixed))
    assert sizes_mm == pytest.approx([300.0, 446.0])
    assert _board_snapshot(doc) == before


def _fresh_unit_selected(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    container = create_unit(doc)
    doc.recompute()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(container)
    return container


def _assert_no_session_left(doc: FreeCAD.Document, objects: int) -> None:
    """No editor session is still open on ``doc``, which holds the
    ``objects`` it held before: nothing was added and no transaction is
    pending."""
    assert len(doc.Objects) == objects
    assert not doc.HasPendingTransaction


def test_edit_unit_refuses_an_unexpected_failure(
    doc: FreeCAD.Document, recorded: list[_Refusal], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_container: FreeCAD.DocumentObject, _view: object) -> None:
        raise RuntimeError("panel exploded")

    _fresh_unit_selected(doc)
    monkeypatch.setattr(panel_module, "EditUnitPanel", fail)
    EditUnitCommand().Activated()

    assert recorded == [
        _Refusal("panel exploded", (), refusals.SUGGESTIONS["unexpected"])
    ]


def test_edit_unit_refuses_a_document_with_no_3d_view(
    doc: FreeCAD.Document, recorded: list[_Refusal], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_unit_selected(doc)
    objects = len(doc.Objects)

    def no_view(_doc: FreeCAD.Document) -> None:
        return None

    monkeypatch.setattr(edit_unit_module, "_view_of", no_view)
    EditUnitCommand().Activated()

    assert len(recorded) == 1, recorded
    assert recorded[0].suggestion == refusals.SUGGESTIONS["no_3d_view"]
    assert not FreeCADGui.Control.activeDialog()
    _assert_no_session_left(doc, objects)


class _OtherTaskPanel:
    """The least a task dialog needs: any other command's panel already
    showing in the Tasks tab."""

    def __init__(self) -> None:
        self.form = QtWidgets.QWidget()


def test_edit_unit_refuses_while_another_task_panel_is_open(
    doc: FreeCAD.Document, recorded: list[_Refusal]
) -> None:
    """``showDialog`` refuses a second task dialog; Edit Unit reports that
    through the helper and cancels the session it had already opened."""
    _fresh_unit_selected(doc)
    before = _board_snapshot(doc)
    objects = len(doc.Objects)
    FreeCADGui.Control.showDialog(_OtherTaskPanel())
    try:
        EditUnitCommand().Activated()
    finally:
        FreeCADGui.Control.closeDialog()

    assert len(recorded) == 1, recorded
    assert recorded[0].summary.startswith("Edit Unit could not open its panel")
    assert recorded[0].objects == ()
    assert recorded[0].suggestion == refusals.SUGGESTIONS["task_panel_open"]
    _assert_no_session_left(doc, objects)
    assert _board_snapshot(doc) == before


def test_a_panel_that_fails_to_build_cancels_its_session(
    doc: FreeCAD.Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: panel_module.EditUnitPanel, _watch: object) -> None:
        raise RuntimeError("form exploded")

    container = _fresh_unit_selected(doc)
    objects = len(doc.Objects)
    monkeypatch.setattr(panel_module.EditUnitPanel, "_build", fail)
    with pytest.raises(RuntimeError, match="form exploded"):
        panel_module.EditUnitPanel(container)
    _assert_no_session_left(doc, objects)


def _refuse_create_unit(doc: FreeCAD.Document, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
        raise RuntimeError("seeding failed")

    monkeypatch.setattr(create_unit_module, "create_unit", fail)
    CreateUnitCommand().Activated()


def _refuse_export_boxes(
    doc: FreeCAD.Document, monkeypatch: pytest.MonkeyPatch
) -> None:
    _overlapping_unit(doc)
    FreeCADGui.Selection.clearSelection()
    for name in ("Overlap", "LeftSide"):
        FreeCADGui.Selection.addSelection(doc.getObject(name))
    ExportBoxesCommand().Activated()


def _refuse_edit_unit(doc: FreeCAD.Document, monkeypatch: pytest.MonkeyPatch) -> None:
    FreeCADGui.Selection.clearSelection()
    EditUnitCommand().Activated()


_Provoke = Callable[[FreeCAD.Document, pytest.MonkeyPatch], None]

# One way to make each toolbar command refuse, and the objects that refusal
# must name. A new toolbar command fails the coverage test until it has one.
_PROVOKERS: dict[str, tuple[_Provoke, tuple[str, ...]]] = {
    "Shelving_CreateUnit": (_refuse_create_unit, ()),
    "Shelving_ExportBoxes": (_refuse_export_boxes, ("Overlap", "LeftSide")),
    "Shelving_EditUnit": (_refuse_edit_unit, ()),
}


def test_every_toolbar_command_has_a_refusal_case() -> None:
    assert set(_PROVOKERS) == set(TOOLBAR_COMMANDS)


@pytest.mark.parametrize("command_id", sorted(_PROVOKERS))
def test_every_command_refuses_through_the_helper(
    command_id: str,
    doc: FreeCAD.Document,
    recorded: list[_Refusal],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provoke, objects = _PROVOKERS[command_id]
    provoke(doc, monkeypatch)
    assert len(recorded) == 1, recorded
    refusal = recorded[0]
    assert refusal.summary
    assert refusal.objects == objects
    assert refusal.suggestion in refusals.SUGGESTIONS.values()
    if objects:
        assert _selected_names() == set(objects)
