"""Typed views of the `*::FeaturePython` property surfaces this package drives.

FreeCAD attaches scripted-object fields with `addProperty` at runtime, and
`freecad-stubs` types `Document.addObject` as a GUI proxy, so a strict type
check has no static view of `NodeId`, `SizeMM`, `Proxy`, and the rest.
`PlankFeature` supplies that view for a plank solid; `ShelvingUnitFeature`
supplies it for the `ShelvingUnit` container (its `App::Part` and the
`ShelvingUnitDriver` child together); `ViewObjectHost` is the `ViewObject` a
Python `ViewProvider` binds to in the GUI, `None` under `freecadcmd`. `plank.py`,
`shelving_unit.py`, and the headless checks import them, so each surface is
declared in one place.
"""

from collections.abc import Sequence
from typing import Protocol

import Part

import FreeCAD


class PlankFeature(Protocol):
    """`Part::FeaturePython` property surface a `Plank` proxy reads and writes.

    The names and types match the `addProperty` calls in `Plank.__init__`.
    """

    Proxy: object
    NodeId: str
    Role: str
    Material: str
    SizeMM: FreeCAD.Vector
    CornerMM: FreeCAD.Vector
    Dimensions: str
    Shape: Part.Shape
    ViewObject: "ViewObjectHost | None"

    def addProperty(
        self,
        type: str,
        name: str,
        group: str = ...,
        doc: str = ...,
        attr: int = ...,
        read_only: bool = ...,
        hidden: bool = ...,
    ) -> "PlankFeature": ...

    def setEditorMode(self, name: str, mode: list[str]) -> None: ...


class ViewObjectHost(Protocol):
    """The `ViewObject` FreeCAD hands a Python `ViewProvider` in `__init__` and
    `attach`.

    `DocumentObject.ViewObject` is `None` under `freecadcmd` (no GUI); in the
    GUI it is a live provider whose `Proxy` binds the Python view provider and
    whose `Object` back-links to the scripted `DocumentObject`.
    """

    Proxy: object
    Object: FreeCAD.DocumentObject


class ShelvingUnitFeature(Protocol):
    """Scripted-object surface of the `ShelvingUnit` container.

    Covers both halves of the container: the `App::Part` that holds the
    single `Placement` and the plank children, and the `ShelvingUnitDriver`
    `App::FeaturePython` child that carries the promoted properties, `Layout`,
    and `execute`. Property names and types match the `addProperty` calls in
    `ShelvingUnit.__init__`; the group / navigation members belong to the
    `App::Part`.
    """

    Proxy: object
    DefaultMaterial: str
    Layout: str
    Name: str
    Label: str
    State: list[str]
    Document: FreeCAD.Document
    Group: list[FreeCAD.DocumentObject]

    # `App::PropertyLength` reads back as a quantity exposing `.Value` in
    # millimetres and accepts a bare number, a string, or a quantity on assign.
    # The annotations are strings: `FreeCAD.Quantity` exists in the stubs but
    # not as a runtime attribute, and the repo forbids `from __future__ import
    # annotations`.
    @property
    def Width(self) -> "FreeCAD.Quantity": ...
    @Width.setter
    def Width(self, value: "FreeCAD.Quantity | float | str") -> None: ...
    @property
    def Height(self) -> "FreeCAD.Quantity": ...
    @Height.setter
    def Height(self, value: "FreeCAD.Quantity | float | str") -> None: ...
    @property
    def Depth(self) -> "FreeCAD.Quantity": ...
    @Depth.setter
    def Depth(self, value: "FreeCAD.Quantity | float | str") -> None: ...

    def addProperty(
        self,
        type: str,
        name: str,
        group: str = ...,
        doc: str = ...,
        attr: int = ...,
        read_only: bool = ...,
        hidden: bool = ...,
        enum_vals: Sequence[str] = ...,
    ) -> "ShelvingUnitFeature": ...

    def setEditorMode(self, name: str, mode: list[str]) -> None: ...

    def addObject(self, obj: FreeCAD.DocumentObject) -> list[object]: ...

    def touch(self) -> None: ...

    def recompute(self, recursive: bool = ...) -> bool: ...

    def getParentGeoFeatureGroup(self) -> "ShelvingUnitFeature | None": ...

    def isValid(self) -> bool: ...
