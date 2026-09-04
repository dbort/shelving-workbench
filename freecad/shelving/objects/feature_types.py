"""Typed view of the `Part::FeaturePython` property surface this package drives.

FreeCAD attaches scripted-object fields with `addProperty` at runtime, and
`freecad-stubs` types `Document.addObject` as a GUI proxy, so a strict type
check has no static view of `NodeId`, `SizeMM`, `Proxy`, and the rest.
`PlankFeature` supplies that view; `plank.py` and the headless checks both
import it, so the surface is declared in one place.
"""

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
