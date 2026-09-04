"""Typed views of the scripted-object property surfaces this package drives.

FreeCAD attaches scripted-object fields with `addProperty` at runtime, and
`freecad-stubs` types `Document.addObject` as a GUI proxy, so a strict type
check has no static view of `NodeId`, `SizeMM`, `Proxy`, and the rest. These
Protocols supply that view. The workbench code and the headless checks both
import them, so each property surface is declared in one place.
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


class ProxyHolder(Protocol):
    """Minimal scripted-object surface: a `Proxy` slot and `touch`."""

    Proxy: object

    def touch(self, propName: str = ...) -> None: ...
