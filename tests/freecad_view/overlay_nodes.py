"""What the in-view editor drew, read back from the Coin scene graph in
document coordinates, so a test checks the nodes the view renders rather
than the plan they were built from."""

from dataclasses import dataclass

import FreeCAD
from pivy import coin

from freecad.Shelving.editor.overlay import Coin as _Coin


def _paths(root: _Coin, type_id: _Coin, hidden: bool = False) -> list[_Coin]:
    """Every path to a node of ``type_id`` under ``root`` that renders, or
    with ``hidden`` also those under a switch showing nothing."""
    search = coin.SoSearchAction()
    search.setType(type_id)
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(hidden)
    search.apply(root)
    found = search.getPaths()
    # The action owns the paths it found and frees them with itself.
    copies = [found[index].copy() for index in range(found.getLength())]
    for path in copies:
        path.ref()
    return copies


def _to_document(path: _Coin, point: tuple[float, float, float]) -> FreeCAD.Vector:
    action = coin.SoGetMatrixAction(coin.SbViewportRegion())
    action.apply(path)
    out = action.getMatrix().multVecMatrix(coin.SbVec3f(*point))
    x, y, z = out.getValue()
    return FreeCAD.Vector(x, y, z)


def faces(root: _Coin) -> list[list[FreeCAD.Vector]]:
    """The corners of every face set under ``root``, in document
    coordinates. Each face set the editor draws has its coordinates just
    before it in the same group."""
    found: list[list[FreeCAD.Vector]] = []
    for path in _paths(root, coin.SoFaceSet.getClassTypeId()):
        group = path.getNodeFromTail(1)
        coordinates = next(
            group.getChild(index)
            for index in range(group.getNumChildren())
            if group.getChild(index).isOfType(coin.SoCoordinate3.getClassTypeId())
        )
        points = [
            tuple(coordinates.point[index].getValue())
            for index in range(coordinates.point.getNum())
        ]
        found.append([_to_document(path, point) for point in points])
    return found


def _sibling(path: _Coin, type_id: _Coin) -> _Coin:
    """The node of ``type_id`` in the group holding ``path``'s tail."""
    group = path.getNodeFromTail(1)
    return next(
        group.getChild(index)
        for index in range(group.getNumChildren())
        if group.getChild(index).isOfType(type_id)
    )


@dataclass(frozen=True)
class Outline:
    rgb: tuple[float, float, float]
    width_px: float
    # The closed outline's points, in document coordinates.
    points: list[FreeCAD.Vector]


def outlines(root: _Coin) -> list[Outline]:
    """Every line set under ``root``. Each line set the editor draws has its
    material, draw style and coordinates just before it in the same group."""
    found: list[Outline] = []
    for path in _paths(root, coin.SoLineSet.getClassTypeId()):
        coordinates = _sibling(path, coin.SoCoordinate3.getClassTypeId())
        material = _sibling(path, coin.SoMaterial.getClassTypeId())
        style = _sibling(path, coin.SoDrawStyle.getClassTypeId())
        color = material.diffuseColor[0].getValue()
        found.append(
            Outline(
                rgb=(float(color[0]), float(color[1]), float(color[2])),
                width_px=float(style.lineWidth.getValue()),
                points=[
                    _to_document(path, tuple(coordinates.point[index].getValue()))
                    for index in range(coordinates.point.getNum())
                ],
            )
        )
    return found


@dataclass(frozen=True)
class Label:
    text: str
    rgb: tuple[float, float, float]
    size: int
    norm: FreeCAD.Vector
    # The two points the dimension spans, in document coordinates.
    points: tuple[FreeCAD.Vector, FreeCAD.Vector]


def labels(root: _Coin) -> list[Label]:
    found: list[Label] = []
    for path in _paths(root, coin.SoType.fromName("SoDatumLabel")):
        node = path.getTail()
        string = node.getField("string")
        color = node.getField("textColor").getValue().getValue()
        norm = node.getField("norm").getValue().getValue()
        pnts = node.getField("pnts")
        ends = [tuple(pnts[index].getValue()) for index in range(pnts.getNum())]
        found.append(
            Label(
                text=str(string[0]),
                rgb=(float(color[0]), float(color[1]), float(color[2])),
                size=int(node.getField("size").getValue()),
                norm=FreeCAD.Vector(*norm),
                points=(_to_document(path, ends[0]), _to_document(path, ends[1])),
            )
        )
    return found


def markers(root: _Coin) -> list[FreeCAD.Vector]:
    """The document point each image under ``root`` is drawn at."""
    return [
        _to_document(path, (0.0, 0.0, 0.0))
        for path in _paths(root, coin.SoImage.getClassTypeId())
    ]


def draggers(root: _Coin) -> int:
    """How many draggers ``root`` holds, shown or not."""
    return len(_paths(root, coin.SoTranslate1Dragger.getClassTypeId(), hidden=True))


def in_scene(scene_graph: _Coin, node: _Coin) -> bool:
    return any(
        scene_graph.getChild(index) == node
        for index in range(scene_graph.getNumChildren())
    )


def bounds(root: _Coin) -> tuple[FreeCAD.Vector, FreeCAD.Vector]:
    """The low and high corners of ``root``'s bounding box, in the
    coordinates of its parent: the box FreeCAD's camera fits its clipping
    planes to."""
    action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 300))
    action.apply(root)
    box = action.getBoundingBox()
    return (
        FreeCAD.Vector(*box.getMin().getValue()),
        FreeCAD.Vector(*box.getMax().getValue()),
    )
