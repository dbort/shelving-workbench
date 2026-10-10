"""Board appearance, which exists only with FreeCAD's GUI up: a new board's
copy of its source board's, Create Unit's color, and a hand-set color
surviving a write (``.claude/docs/freecad-notes.md``, "A ``DocumentObject``'s
``ViewObject`` is ``None``")."""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.session import Session
from freecad.Shelving.unit_ops import create_unit, resize_unit

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
    # freecad-stubs leaves the App.Material constructor unannotated.
    material = FreeCAD.Material()  # type: ignore[no-untyped-call]
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
        session.cancel()


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
