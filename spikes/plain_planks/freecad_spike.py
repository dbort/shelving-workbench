"""Plain-planks spike, FreeCAD half: plain boxes carrying our metadata.

Run with ``freecadcmd spikes/plain_planks/freecad_spike.py``. ``freecadcmd``
discards a script's exit status (``docs/freecadcmd-notes.md``), so the final
``plain-planks freecad spike OK`` line is the only success signal.

It answers the four FreeCAD spike goals in
``docs/parametric-model-evaluation.md``: that dynamic properties survive a save
and reload on a plain ``Part::Box`` with nothing of ours in the file, that a
container walk produces the recogniser's input from both an ``App::Part`` and an
``App::LinkGroup``, that apply updates and removes boxes by identity, and what a
forty-plank unit costs.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import zipfile
from pkgutil import extend_path
from typing import Any, NamedTuple, Protocol, cast

import FreeCAD

import freecad

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
freecad.__path__ = extend_path(freecad.__path__, "freecad")

from shelving_core.expand import expand  # noqa: E402
from shelving_core.layout import (  # noqa: E402
    Carcass,
    Divider,
    Fill,
    Leaf,
    Orientation,
    Split,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId  # noqa: E402
from spikes.plain_planks.export_boxes import export_container  # noqa: E402
from spikes.plain_planks.recognise import (  # noqa: E402
    Box,
    recognise,
    to_carcass,
)

PLY18 = MaterialId("ply18")
CATALOG = Catalog(entries={PLY18: MaterialEntry(PLY18, "ply 18", 18.0, "plywood")})
MATERIAL_FOR_THICKNESS = {18.0: PLY18}

# The metadata apply would write on each plain box. Strings only: they need no
# schema and survive a reload with no proxy to restore them.
_META = ("ShelvingNodeId", "ShelvingRole", "ShelvingRule", "ShelvingMaterial")


def _add_box(
    doc: FreeCAD.Document,
    name: str,
    corner_mm: tuple[float, float, float],
    size_mm: tuple[float, float, float],
) -> FreeCAD.DocumentObject:
    obj = doc.addObject("Part::Box", name)
    typed = _box(obj)
    typed.Length, typed.Width, typed.Height = size_mm
    typed.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0)
    )
    return _obj(obj)


class TaggedBox(Protocol):
    """The ``Part::Box`` surface the spike reads and writes, including the four
    dynamic properties apply stamps on each plank."""

    Name: str
    Label: str
    TypeId: str
    Placement: FreeCAD.Placement
    Length: float
    Width: float
    Height: float
    Shape: Any
    ShelvingNodeId: str
    ShelvingRole: str
    ShelvingRule: str
    ShelvingMaterial: str

    def addProperty(  # noqa: N802
        self, type_: str, name: str, group: str, doc: str
    ) -> object: ...


class Container(Protocol):
    """The container surface: ``App::Part`` exposes ``Group``, ``App::LinkGroup``
    ``ElementList`` plus ``setLink``."""

    Name: str
    Label: str
    TypeId: str
    Placement: FreeCAD.Placement
    Group: list[FreeCAD.DocumentObject]

    def setLink(self, objects: list[FreeCAD.DocumentObject]) -> None: ...


def _box(obj: FreeCAD.DocumentObject) -> TaggedBox:
    return cast("TaggedBox", obj)


def _container(obj: FreeCAD.DocumentObject) -> Container:
    return cast("Container", obj)


def _obj(value: object) -> FreeCAD.DocumentObject:
    return cast("FreeCAD.DocumentObject", value)


def _tag(obj: FreeCAD.DocumentObject, node_id: str, role: str, rule: str) -> None:
    box = _box(obj)
    for prop in _META:
        box.addProperty("App::PropertyString", prop, "Shelving", "plain-planks spike")
    box.ShelvingNodeId = node_id
    box.ShelvingRole = role
    box.ShelvingRule = rule
    box.ShelvingMaterial = str(PLY18)


class PlankRecord(NamedTuple):
    """One plank of a sample unit, in the form ``_build_unit`` consumes."""

    name: str
    corner_mm: tuple[float, float, float]
    size_mm: tuple[float, float, float]
    node_id: str
    role: str


def _unit_boxes(carcass: Carcass) -> list[PlankRecord]:
    return [
        PlankRecord(
            name=f"Plank{index:03d}",
            corner_mm=(spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm),
            size_mm=(spec.size.x_mm, spec.size.y_mm, spec.size.z_mm),
            node_id=spec.node_id,
            role=spec.role.value,
        )
        for index, spec in enumerate(expand(carcass, CATALOG))
    ]


def goal_6_properties_survive_reload() -> None:
    """Dynamic properties on a plain ``Part::Box`` persist with nothing of ours
    in the saved file."""
    doc = FreeCAD.newDocument("plain_planks_persist")
    obj = _add_box(doc, "Shelf", (0.0, 0.0, 100.0), (500.0, 300.0, 18.0))
    _tag(obj, "node-abc", "shelf", "fill")
    # Both names must be read before the close: the Python wrappers go stale
    # with the document.
    box_name = obj.Name
    doc_name = doc.Name
    path = os.path.join(tempfile.mkdtemp(), "persist.FCStd")
    doc.saveAs(path)
    FreeCAD.closeDocument(doc_name)

    # A document that carried a Python proxy would need our modules installed
    # to load cleanly. The property group name is our word "Shelving" and is
    # inert, so the check looks for the proxy machinery, not the name.
    with zipfile.ZipFile(path) as archive:
        payload = archive.read("Document.xml").decode("utf-8", "replace")
    for needle in ("Proxy", "FeaturePython", "PythonObject", "spikes."):
        assert needle not in payload, f"saved document mentions {needle!r}"

    reopened = FreeCAD.openDocument(path)
    back = reopened.getObject(box_name)
    assert back is not None, "the box did not survive the reload"
    restored = _box(back)
    assert restored.TypeId == "Part::Box", restored.TypeId
    assert restored.ShelvingNodeId == "node-abc"
    assert restored.ShelvingRole == "shelf"
    assert restored.ShelvingRule == "fill"
    assert restored.ShelvingMaterial == "ply18"
    assert restored.Shape.Volume > 0.0
    FreeCAD.closeDocument(reopened.Name)
    os.remove(path)
    print("goal 6 OK: dynamic properties survive a reload, file names nothing of ours")


def _build_unit(
    doc: FreeCAD.Document, carcass: Carcass, container_type: str, label: str
) -> FreeCAD.DocumentObject:
    boxes: list[FreeCAD.DocumentObject] = []
    for record in _unit_boxes(carcass):
        obj = _add_box(doc, record.name, record.corner_mm, record.size_mm)
        _tag(obj, record.node_id, record.role, "fill")
        boxes.append(obj)
    container = doc.addObject(container_type, "Unit")
    typed_container = _container(container)
    typed_container.Label = label
    if container_type == "App::LinkGroup":
        typed_container.setLink(boxes)
    else:
        typed_container.Group = boxes
    doc.recompute()
    return _obj(container)


def goal_7_export_from_containers() -> None:
    """The container walk feeds the core recogniser from both container types,
    including a container that has been moved."""
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1200.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf(), Leaf()],
            rules=[Fill(), Fill(), Fill()],
            dividers=[Divider(), Divider()],
        ),
    )
    doc = FreeCAD.newDocument("plain_planks_export")
    for container_type in ("App::Part", "App::LinkGroup"):
        container = _build_unit(doc, carcass, container_type, f"Unit {container_type}")
        export = export_container(container)
        assert not export["skipped"], export["skipped"]
        boxes = [
            Box(
                name=record["name"],
                corner_mm=cast(
                    "tuple[float, float, float]", tuple(record["corner_mm"])
                ),
                size_mm=cast("tuple[float, float, float]", tuple(record["size_mm"])),
            )
            for record in export["boxes"]
        ]
        recovered = to_carcass(recognise(boxes), MATERIAL_FOR_THICKNESS)
        assert isinstance(recovered.root, Split), container_type
        assert len(recovered.root.children) == 3, container_type
        assert recovered.width_mm == 900.0 and recovered.height_mm == 1200.0

        # Moving the container must not change the recognised tree: the walk
        # composes container placements and the tree is measured relative to
        # its own bounding rectangle.
        _container(container).Placement = FreeCAD.Placement(
            FreeCAD.Vector(1000.0, 50.0, 25.0), FreeCAD.Rotation()
        )
        doc.recompute()
        moved = export_container(container)
        shifted = [
            Box(
                name=record["name"],
                corner_mm=cast(
                    "tuple[float, float, float]", tuple(record["corner_mm"])
                ),
                size_mm=cast("tuple[float, float, float]", tuple(record["size_mm"])),
            )
            for record in moved["boxes"]
        ]
        after = to_carcass(recognise(shifted), MATERIAL_FOR_THICKNESS)
        assert isinstance(after.root, Split)
        assert len(after.root.children) == 3, f"{container_type} after move"
        first = shifted[0].corner_mm
        assert first[0] >= 1000.0, f"{container_type}: container offset not applied"
        print(
            f"goal 7 OK: {container_type} exports {len(boxes)} boxes, survives a move"
        )
    FreeCAD.closeDocument(doc.Name)


def _apply(
    doc: FreeCAD.Document, container: FreeCAD.DocumentObject, carcass: Carcass
) -> tuple[int, int, int]:
    """Write ``carcass`` into ``container``, matching boxes by node id.

    Returns the counts of updated, created, and removed boxes.
    """
    existing = {}
    for child in export_children(container):
        node_id = getattr(child, "ShelvingNodeId", None)
        if isinstance(node_id, str) and node_id:
            existing[node_id] = child
    updated = created = 0
    seen = set()
    for spec in expand(carcass, CATALOG):
        seen.add(spec.node_id)
        obj = existing.get(spec.node_id)
        if obj is None:
            obj = _add_box(
                doc,
                "Plank",
                (spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm),
                (spec.size.x_mm, spec.size.y_mm, spec.size.z_mm),
            )
            _tag(obj, spec.node_id, spec.role.value, "fill")
            _attach(container, obj)
            created += 1
            continue
        typed = _box(obj)
        typed.Length = spec.size.x_mm
        typed.Width = spec.size.y_mm
        typed.Height = spec.size.z_mm
        typed.Placement = FreeCAD.Placement(
            FreeCAD.Vector(
                spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm
            ),
            FreeCAD.Rotation(),
        )
        typed.ShelvingRole = spec.role.value
        updated += 1
    removed = 0
    for node_id, obj in existing.items():
        if node_id not in seen:
            doc.removeObject(obj.Name)
            removed += 1
    doc.recompute()
    return updated, created, removed


def export_children(container: FreeCAD.DocumentObject) -> list[FreeCAD.DocumentObject]:
    for attr in ("ElementList", "Group"):
        members = getattr(container, attr, None)
        if isinstance(members, list):
            return [m for m in members if isinstance(m, FreeCAD.DocumentObject)]
    return []


def _attach(container: FreeCAD.DocumentObject, obj: FreeCAD.DocumentObject) -> None:
    typed = _container(container)
    if typed.TypeId == "App::LinkGroup":
        typed.setLink([*export_children(container), obj])
    else:
        typed.Group = [*export_children(container), obj]


def goal_8_apply_by_identity() -> None:
    """Apply updates untouched boxes in place, creates only the new plank, and
    deletes only the removed one."""
    two_shelves = Carcass(
        width_mm=900.0,
        height_mm=1200.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf(), Leaf()],
            rules=[Fill(), Fill(), Fill()],
            dividers=[Divider(), Divider()],
        ),
    )
    doc = FreeCAD.newDocument("plain_planks_apply")
    container = _build_unit(doc, two_shelves, "App::Part", "Apply Unit")
    before = {child.Name for child in export_children(container)}
    keep = {
        _box(child).ShelvingNodeId: child.Name
        for child in export_children(container)
        if _box(child).ShelvingRole in ("bottom", "top", "left_side", "right_side")
    }

    root = two_shelves.root
    assert isinstance(root, Split)
    three_shelves = Carcass(
        width_mm=two_shelves.width_mm,
        height_mm=two_shelves.height_mm,
        depth_mm=two_shelves.depth_mm,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.HORIZONTAL,
            children=[*root.children, Leaf()],
            rules=[Fill(), Fill(), Fill(), Fill()],
            dividers=[*root.dividers, Divider()],
        ),
        id=two_shelves.id,
    )
    updated, created, removed = _apply(doc, container, three_shelves)
    assert created == 1, created
    assert removed == 0, removed
    after = {child.Name for child in export_children(container)}
    assert before < after, "adding a shelf must keep every existing object"
    for node_id, name in keep.items():
        match = [
            c for c in export_children(container) if _box(c).ShelvingNodeId == node_id
        ]
        assert len(match) == 1 and match[0].Name == name, node_id

    # Removing the added shelf deletes exactly that object.
    updated, created, removed = _apply(doc, container, two_shelves)
    assert created == 0 and removed == 1, (created, removed)
    assert {child.Name for child in export_children(container)} == before

    # The applied unit still recognises, so an edit cycle is closed.
    export = export_container(container)
    boxes = [
        Box(
            name=record["name"],
            corner_mm=cast("tuple[float, float, float]", tuple(record["corner_mm"])),
            size_mm=cast("tuple[float, float, float]", tuple(record["size_mm"])),
        )
        for record in export["boxes"]
    ]
    again = to_carcass(recognise(boxes), MATERIAL_FOR_THICKNESS)
    assert isinstance(again.root, Split) and len(again.root.children) == 3
    FreeCAD.closeDocument(doc.Name)
    print(
        f"goal 8 OK: apply updated {updated}, created and removed one plank by id, "
        "and the result still recognises"
    )


def goal_9_scale() -> None:
    """A forty-plank unit's export, recognise, and apply cost."""
    carcass = Carcass(
        width_mm=2000.0,
        height_mm=2000.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.VERTICAL,
            children=[
                Split(
                    orientation=Orientation.HORIZONTAL,
                    children=[Leaf() for _ in range(7)],
                    rules=[Fill() for _ in range(7)],
                    dividers=[Divider() for _ in range(6)],
                )
                for _ in range(6)
            ],
            rules=[Fill() for _ in range(6)],
            dividers=[Divider() for _ in range(5)],
        ),
    )
    doc = FreeCAD.newDocument("plain_planks_scale")
    start = time.perf_counter()
    container = _build_unit(doc, carcass, "App::Part", "Scale Unit")
    build_s = time.perf_counter() - start

    start = time.perf_counter()
    export = export_container(container)
    export_s = time.perf_counter() - start
    boxes = [
        Box(
            name=record["name"],
            corner_mm=cast("tuple[float, float, float]", tuple(record["corner_mm"])),
            size_mm=cast("tuple[float, float, float]", tuple(record["size_mm"])),
        )
        for record in export["boxes"]
    ]
    start = time.perf_counter()
    recovered = to_carcass(recognise(boxes), MATERIAL_FOR_THICKNESS)
    recognise_s = time.perf_counter() - start

    wider = Carcass(
        width_mm=2400.0,
        height_mm=carcass.height_mm,
        depth_mm=carcass.depth_mm,
        default_material=PLY18,
        root=recovered.root,
        id=recovered.id,
    )
    start = time.perf_counter()
    _apply(doc, container, wider)
    apply_s = time.perf_counter() - start
    print(
        f"goal 9 OK: {len(boxes)} planks -- build {build_s * 1000:.0f} ms, "
        f"export {export_s * 1000:.1f} ms, recognise {recognise_s * 1000:.1f} ms, "
        f"apply+recompute {apply_s * 1000:.0f} ms"
    )
    FreeCAD.closeDocument(doc.Name)


goal_6_properties_survive_reload()
goal_7_export_from_containers()
goal_8_apply_by_identity()
goal_9_scale()
print("plain-planks freecad spike OK")
