"""Board appearance, which exists only with FreeCAD's GUI up: a new board's
copy of its source board's, Create Unit's color, a hand-set color
surviving a write, and the colors a stock swap paints
(``.claude/docs/freecad-notes.md``, "A ``DocumentObject``'s ``ViewObject``
is ``None``")."""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving import properties
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.session import Session
from freecad.Shelving.unit_ops import create_unit, resize_unit
from tests.freecad_materials import library_material

_MAGIC_START_RGB = (247, 185, 108)
_BOARDS = ("bottom", "top", "left_side", "right_side")

_Appearance = tuple[tuple[float, ...], float, float]


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float


class _AppearanceView(Protocol):
    ShapeAppearance: list[FreeCAD.Material]


@pytest.fixture
def doc(request: pytest.FixtureRequest) -> Iterator[FreeCAD.Document]:
    document = FreeCAD.newDocument(request.node.name)
    yield document
    FreeCAD.closeDocument(document.Name)


def _view(doc: FreeCAD.Document, name: str) -> _AppearanceView:
    obj = doc.getObject(name)
    assert obj is not None
    assert obj.ViewObject is not None
    return cast("_AppearanceView", obj.ViewObject)


def _appearance(view: _AppearanceView) -> list[_Appearance]:
    """Each face's diffuse color, transparency and shininess."""
    return [
        (tuple(m.DiffuseColor[:3]), m.Transparency, m.Shininess)
        for m in view.ShapeAppearance
    ]


def _material(rgb: tuple[float, float, float]) -> FreeCAD.Material:
    material = FreeCAD.Material()
    material.DiffuseColor = (*rgb, 1.0)
    return material


def _first_bay_id(region: Region) -> str:
    if isinstance(region, Bay):
        return region.id
    assert isinstance(region, Division)
    return next(
        _first_bay_id(item)
        for item in region.items
        if isinstance(item, Bay | Division) and _has_bay(item)
    )


def _has_bay(region: Region) -> bool:
    if isinstance(region, Bay):
        return True
    if isinstance(region, Division):
        return any(
            _has_bay(item) for item in region.items if not isinstance(item, Board)
        )
    return False


def _board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    ids: set[str] = set()
    for item in region.items:
        if isinstance(item, Board):
            ids.add(item.id)
        else:
            ids |= _board_ids(item)
    return ids


def test_create_unit_boards_are_18_mm_in_magic_start_color(
    doc: FreeCAD.Document,
) -> None:
    create_unit(doc)
    doc.recompute()
    for name in _BOARDS:
        box = cast("_BoxFeature", doc.getObject(name))
        assert min(float(box.Length), float(box.Width), float(box.Height)) == (
            pytest.approx(18.0)
        )
        for diffuse, _transparency, _shininess in _appearance(_view(doc, name)):
            assert diffuse == pytest.approx(
                tuple(c / 255 for c in _MAGIC_START_RGB), abs=1e-3
            ), name


def test_a_new_board_copies_its_source_boards_whole_appearance(
    doc: FreeCAD.Document,
) -> None:
    """The first shelf in a new unit copies the bottom board, per-face
    colors, transparency and shininess included."""
    container = create_unit(doc)
    doc.recompute()
    bottom = _view(doc, "bottom")
    faces = [_material((0.1 * i, 0.5, 1.0 - 0.1 * i)) for i in range(6)]
    faces[2].Transparency = 0.5
    faces[3].Shininess = 0.75
    bottom.ShapeAppearance = faces
    expected = _appearance(bottom)

    session = Session(container)
    session.open()
    try:
        before = _board_ids(session.unit.root)
        session.select(_first_bay_id(session.unit.root))
        assert session.split("vertical") is None
        doc.recompute()
        (new_id,) = _board_ids(session.unit.root) - before
        assert _appearance(_view(doc, new_id)) == pytest.approx(expected)
    finally:
        session.close()


def test_a_new_shelf_keeps_its_color_through_undo_redo_and_close(
    doc: FreeCAD.Document,
) -> None:
    doc.UndoMode = 1
    container = create_unit(doc)
    doc.recompute()
    bottom = _view(doc, "bottom")
    bottom.ShapeAppearance = [_material((0.2, 0.6, 0.3))]
    expected = _appearance(bottom)

    session = Session(container)
    session.open()
    before = _board_ids(session.unit.root)
    session.select(_first_bay_id(session.unit.root))
    assert session.split("vertical") is None
    (shelf,) = _board_ids(session.unit.root) - before
    session.select(_first_bay_id(session.unit.root))
    assert session.set_size(250.0) is None
    doc.undo()
    session.settle()
    doc.redo()
    session.settle()
    assert _appearance(_view(doc, shelf)) == pytest.approx(expected)
    session.close()
    assert _appearance(_view(doc, shelf)) == pytest.approx(expected)


def test_a_resize_keeps_a_hand_set_board_color(doc: FreeCAD.Document) -> None:
    container = create_unit(doc)
    doc.recompute()
    top = _view(doc, "top")
    top.ShapeAppearance = [_material((0.2, 0.4, 0.6))]
    expected = _appearance(top)

    resize_unit(container, Vec3(700.0, 300.0, 1000.0))
    doc.recompute()

    assert float(cast("_BoxFeature", doc.getObject("top")).Length) == pytest.approx(
        700.0
    )
    assert _appearance(top) == pytest.approx(expected)


def _swap_session(doc: FreeCAD.Document) -> Session:
    """An open session on a new unit with every board selected."""
    container = create_unit(doc)
    doc.recompute()
    session = Session(container)
    session.open()
    session.select_boards(sorted(_board_ids(session.unit.root)))
    return session


def _diffuse_rgb(view: _AppearanceView) -> set[tuple[float, ...]]:
    """Each distinct diffuse color among the faces, rounded to 0 to 255."""
    return {
        tuple(round(c * 255) for c in diffuse) for diffuse, _t, _s in _appearance(view)
    }


def test_a_material_swap_repaints_in_the_materials_color(
    doc: FreeCAD.Document,
) -> None:
    session = _swap_session(doc)
    try:
        wood = library_material("Wood")
        assert session.swap_stock(material_uuid=wood.UUID) is None
        expected = properties.material_color(wood)
        assert expected is not None and expected != _MAGIC_START_RGB
        for name in _BOARDS:
            assert _diffuse_rgb(_view(doc, name)) == {expected}, name
        assert {group.color for group in session.stock_groups()} == {expected}
    finally:
        session.close()


def test_an_explicit_color_wins_over_the_materials(doc: FreeCAD.Document) -> None:
    session = _swap_session(doc)
    try:
        wood = library_material("Wood")
        assert session.swap_stock(material_uuid=wood.UUID, color=(10, 120, 200)) is None
        for name in _BOARDS:
            assert _diffuse_rgb(_view(doc, name)) == {(10, 120, 200)}, name
    finally:
        session.close()


def test_a_swap_replaces_per_face_colors(doc: FreeCAD.Document) -> None:
    session = _swap_session(doc)
    try:
        top = _view(doc, "top")
        top.ShapeAppearance = [
            _material((0.1 * i, 0.5, 1.0 - 0.1 * i)) for i in range(6)
        ]
        session.select_boards(["top"])
        assert session.swap_stock(color=(40, 50, 60)) is None
        assert _diffuse_rgb(top) == {(40, 50, 60)}
        top.ShapeAppearance = [
            _material((0.1 * i, 0.5, 1.0 - 0.1 * i)) for i in range(6)
        ]
        assert session.swap_stock(material_uuid=library_material("Wood").UUID) is None
        assert len(_diffuse_rgb(top)) == 1
    finally:
        session.close()


def test_the_stock_groups_tell_colors_apart(doc: FreeCAD.Document) -> None:
    session = _swap_session(doc)
    try:
        (group,) = session.stock_groups()
        assert group.color == _MAGIC_START_RGB
        session.select_boards(["top"])
        assert session.swap_stock(color=(1, 2, 3)) is None
        groups = session.stock_groups()
        assert [(g.board_ids, g.color) for g in groups][1] == (("top",), (1, 2, 3))
    finally:
        session.close()
