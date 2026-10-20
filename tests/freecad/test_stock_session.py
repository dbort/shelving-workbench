"""The session's stock list, its multi-board selection and the stock swap,
on a copy of the Woodworking workbench's Magic Start unit. Without a GUI no
board has a color, so these cover thickness and material only;
``tests/freecad_gui/test_stock.py`` covers color."""

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving import properties
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.session import Session
from tests.freecad_materials import library_material

_MAGIC_START = (
    Path(__file__).parent / "fixtures" / "woodworking_magic_start_default.FCStd"
)
_LAYOUT_BOARDS = ("Floor", "Left", "Right", "Top", "Shelf")


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


class _GrainObject(Protocol):
    Grain: list[str]


_Snapshot = dict[str, tuple[float, float, float, float, float, float, str | None]]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    path = tmp_path / _MAGIC_START.name
    shutil.copyfile(_MAGIC_START, path)
    doc = FreeCAD.openDocument(str(path))
    container = doc.getObject("LinkGroup")
    assert container is not None
    opened = Session(container)
    opened.open()
    yield opened
    opened.close()
    FreeCAD.closeDocument(doc.Name)


def _snapshot(session: Session) -> _Snapshot:
    """Each board's size, position and material name."""
    doc = session.container.Document
    out: _Snapshot = {}
    for name in _LAYOUT_BOARDS:
        obj = doc.getObject(name)
        assert obj is not None
        box = cast("_BoxFeature", obj)
        base = box.Placement.Base
        out[name] = (
            float(box.Length),
            float(box.Width),
            float(box.Height),
            float(base.x),
            float(base.y),
            float(base.z),
            properties.read_material_name(obj),
        )
    return out


def _bay_ids(region: Region) -> list[str]:
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


def test_the_magic_start_boards_are_one_stock_and_the_back_is_in_none(
    session: Session,
) -> None:
    (group,) = session.stock_groups()
    assert sorted(group.board_ids) == sorted(_LAYOUT_BOARDS)
    assert group.thickness_mm == pytest.approx(18.0)
    assert group.material == "Default"
    assert group.color is None
    assert "Back" in {entry.name for entry in session.untagged}


def test_two_selected_boards_are_no_single_selection(session: Session) -> None:
    session.select_boards(["Shelf", "Top"])
    assert session.selected_boards == ("Shelf", "Top")
    assert session.selected_id is None
    assert not session.can_split()
    assert not session.can_merge()
    assert session.selected_measurement() is None
    session.select_boards(["Shelf"])
    assert session.selected_id == "Shelf"
    assert session.selected_boards == ("Shelf",)
    assert session.can_merge()


def test_a_swap_of_the_shelf_makes_it_its_own_stock(session: Session) -> None:
    doc = session.container.Document
    wood = library_material("Wood")
    session.select_boards(["Shelf"])
    steps = doc.UndoCount
    assert session.swap_stock(thickness_mm=12.0, material_uuid=wood.UUID) is None
    doc.recompute()
    assert doc.UndoCount == steps + 1
    assert session.selected_boards == ("Shelf",)
    groups = session.stock_groups()
    assert [sorted(group.board_ids) for group in groups] == [
        sorted(set(_LAYOUT_BOARDS) - {"Shelf"}),
        ["Shelf"],
    ]
    assert groups[1].thickness_mm == pytest.approx(12.0)
    assert groups[1].material == "Wood"
    shelf = cast("_BoxFeature", doc.getObject("Shelf"))
    assert float(shelf.Height) == pytest.approx(12.0)


def test_one_undo_takes_back_a_swap_of_several_boards(session: Session) -> None:
    doc = session.container.Document
    doc.recompute()
    before = _snapshot(session)
    session.select_boards(["Floor", "Shelf", "Top"])
    wood = library_material("Wood")
    assert session.swap_stock(thickness_mm=15.0, material_uuid=wood.UUID) is None
    doc.recompute()
    assert _snapshot(session) != before
    doc.undo()
    session.settle()
    doc.recompute()
    assert _snapshot(session) == before
    # The rescan an Undo makes keeps every selected board.
    assert session.selected_boards == ("Floor", "Shelf", "Top")


def test_a_swap_that_cannot_fit_changes_no_board(session: Session) -> None:
    doc = session.container.Document
    doc.recompute()
    before = _snapshot(session)
    steps = doc.UndoCount
    session.select_boards(["Floor", "Shelf", "Top"])
    wood = library_material("Wood")
    failure = session.swap_stock(thickness_mm=300.0, material_uuid=wood.UUID)
    assert failure is not None and failure.message
    doc.recompute()
    assert _snapshot(session) == before
    assert doc.UndoCount == steps


def test_a_swap_with_nothing_set_changes_nothing(session: Session) -> None:
    doc = session.container.Document
    steps = doc.UndoCount
    session.select_boards(["Shelf", "Top"])
    assert session.swap_stock() is None
    assert doc.UndoCount == steps
    assert session.selected_boards == ("Shelf", "Top")


def test_a_swap_never_touches_grain(session: Session) -> None:
    doc = session.container.Document
    shelf = doc.getObject("Shelf")
    assert shelf is not None
    shelf.addProperty("App::PropertyStringList", "Grain", "Woodworking")
    grain = ["H", "V", "H", "V", "X", "X"]
    cast("_GrainObject", shelf).Grain = grain
    session.select_boards(["Shelf"])
    wood = library_material("Wood")
    assert session.swap_stock(thickness_mm=12.0, material_uuid=wood.UUID) is None
    assert session.swap_stock(color=(10, 20, 30)) is None
    assert properties.read_grain(shelf) == grain


def test_an_unknown_material_is_refused(session: Session) -> None:
    session.select_boards(["Shelf"])
    failure = session.swap_stock(material_uuid="not-a-material")
    assert failure is not None


def test_two_inner_boards_delete_as_one_step(session: Session) -> None:
    doc = session.container.Document
    lower = _bay_ids(session.unit.root)[0]
    session.select(lower)
    assert session.split("vertical") is None
    added = next(
        board
        for board in session.stock_groups()[0].board_ids
        if board not in _LAYOUT_BOARDS
    )
    steps = doc.UndoCount
    session.select_boards(["Shelf", added])
    assert session.delete_boards() is None
    assert doc.UndoCount == steps + 1
    assert session.selected_boards == ()
    assert doc.getObject("Shelf") is None
    assert doc.getObject(added) is None


def test_a_refused_board_refuses_the_whole_delete(session: Session) -> None:
    doc = session.container.Document
    steps = doc.UndoCount
    session.select_boards(["Shelf", "Left"])
    failure = session.delete_boards()
    assert failure is not None and failure.node_id == "Left"
    assert doc.getObject("Shelf") is not None
    assert doc.UndoCount == steps
