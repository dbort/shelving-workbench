"""Headless functional check for the shelving object layer.

Run via ``freecadcmd tools/freecad_object_smoke.py``. One check probes whether a
recomputing ``App::Part`` invokes a Python ``Proxy.execute`` (see the
"``App::Part`` does not call a Python ``Proxy.execute``" section of
``docs/freecadcmd-notes.md``). ``freecadcmd`` discards a script's exit status, so
the final ``shelving object layer OK`` line is the only success signal;
``tools/run-tests.sh`` greps for it.

The ``sys.path`` insert plus ``freecad.__path__`` refresh mirror
``tools/freecad_smoke.py``: FreeCAD freezes the ``freecad`` namespace package's
``__path__`` at start-up, so a checkout-resident ``freecad.shelving`` needs the
path merged back in before it imports.
"""

import os
import sys
from pkgutil import extend_path
from typing import cast

import FreeCAD
import freecad

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
freecad.__path__ = extend_path(freecad.__path__, "freecad")

from freecad.shelving.catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_CATALOG_IDS,
    DEFAULT_MATERIAL_ID,
)
from freecad.shelving.objects.feature_types import (  # noqa: E402
    PlankFeature,
    ProxyHolder,
)
from freecad.shelving.objects.geometry import plank_shape  # noqa: E402
from freecad.shelving.objects.labels import generated_label  # noqa: E402
from freecad.shelving.objects.plank import add_plank  # noqa: E402
from freecad.shelving.vendor.shelving_core.expand import (  # noqa: E402
    PlankRole,
    Vec3,
)

_CATALOG_ORDER = ["ply18", "ply12", "mdf19", "hardwood20"]

# Whether FreeCAD 1.0 under freecadcmd calls a Python ``Proxy.execute`` when an
# ``App::Part`` recomputes. Hard-coded from the observed probe result recorded
# in the "``App::Part`` does not call a Python ``Proxy.execute``" section of
# docs/freecadcmd-notes.md; a FreeCAD bump that flips this fails `pixi run tests`
# and forces sh-012's container design to be revisited.
EXPECTED_APART_EXECUTE = False

# App::* types that ship a Python scripted-object extension. Attaching a Proxy to
# any of these and recomputing must call ``Proxy.execute``; they are the probe's
# positive control, so a FreeCAD that silently stopped dispatching ``execute``
# fails here instead of letting the ``App::Part`` result pass vacuously.
_PYTHON_FEATURE_TYPES = (
    "App::FeaturePython",
    "App::GeometryPython",
    "App::DocumentObjectGroupPython",
)


class _Recorder:
    """Scripted-object proxy that records whether ``execute`` fired on recompute."""

    def __init__(self) -> None:
        self.executed = False

    def execute(self, obj: object) -> None:
        self.executed = True


def _assert_box(
    bound_box: FreeCAD.BoundBox,
    min_corner_mm: tuple[float, float, float],
    max_corner_mm: tuple[float, float, float],
    tol_mm: float = 1e-6,
) -> None:
    observed = (
        bound_box.XMin,
        bound_box.YMin,
        bound_box.ZMin,
        bound_box.XMax,
        bound_box.YMax,
        bound_box.ZMax,
    )
    expected = min_corner_mm + max_corner_mm
    for got_mm, want_mm in zip(observed, expected, strict=True):
        assert abs(got_mm - want_mm) <= tol_mm, (observed, expected)


def _check_labels() -> None:
    assert generated_label(PlankRole.BOTTOM, 0) == "Bottom"
    assert generated_label(PlankRole.TOP, 0) == "Top"
    assert generated_label(PlankRole.LEFT_SIDE, 0) == "Left Side"
    assert generated_label(PlankRole.RIGHT_SIDE, 0) == "Right Side"
    assert generated_label(PlankRole.SHELF, 2) == "Shelf 2"
    assert generated_label(PlankRole.DIVIDER, 3) == "Divider 3"


def _check_catalog() -> None:
    ids = [str(entry.id) for entry in DEFAULT_CATALOG]
    assert ids == _CATALOG_ORDER, ids
    assert DEFAULT_CATALOG_IDS == _CATALOG_ORDER, DEFAULT_CATALOG_IDS
    ply18 = DEFAULT_CATALOG["ply18"]
    assert ply18.thickness_mm == 18.0, ply18.thickness_mm
    assert ply18.name == "18 mm birch plywood", ply18.name
    assert DEFAULT_MATERIAL_ID == "ply18", DEFAULT_MATERIAL_ID


def _check_plank_shape() -> None:
    shape = plank_shape(Vec3(700.0, 300.0, 18.0), Vec3(10.0, 0.0, 5.0))
    assert shape.ShapeType == "Solid", shape.ShapeType
    _assert_box(shape.BoundBox, (10.0, 0.0, 5.0), (710.0, 300.0, 23.0))
    try:
        plank_shape(Vec3(0.0, 1.0, 1.0), Vec3(0.0, 0.0, 0.0))
    except ValueError:
        pass
    else:
        raise AssertionError("plank_shape accepted a zero extent")


def _check_plank_recompute() -> None:
    doc = FreeCAD.newDocument("shelving_smoke")
    try:
        obj = cast("PlankFeature", add_plank(doc))
        obj.SizeMM = FreeCAD.Vector(700.0, 300.0, 18.0)
        obj.CornerMM = FreeCAD.Vector(10.0, 0.0, 5.0)
        doc.recompute()
        _assert_box(obj.Shape.BoundBox, (10.0, 0.0, 5.0), (710.0, 300.0, 23.0))
        assert obj.Dimensions == "700 x 300 x 18 mm", obj.Dimensions
    finally:
        FreeCAD.closeDocument(doc.Name)


def _apart_rejects_proxy_attr() -> bool:
    """Attach a proxy to a bare ``App::Part`` with ``part.Proxy = recorder``.

    Returns whether ``_Recorder.execute`` fired on the following recompute.
    FreeCAD 1.0 rejects the assignment with ``AttributeError`` (the C++ type
    carries no ``App::*Python`` extension), so the recorder can never fire.
    """
    doc = FreeCAD.newDocument("shelving_probe_attr")
    try:
        recorder = _Recorder()
        part = cast("ProxyHolder", doc.addObject("App::Part", "Probe"))
        try:
            part.Proxy = recorder
        except AttributeError:
            return False
        part.touch()
        doc.recompute()
        return recorder.executed
    finally:
        FreeCAD.closeDocument(doc.Name)


def _apart_ignores_proxy_arg() -> bool:
    """Attach a proxy to an ``App::Part`` through the three-argument
    ``doc.addObject("App::Part", name, recorder)`` form.

    Returns whether ``_Recorder.execute`` fired on the following recompute. The
    call does not raise, but the resulting C++ ``App::Part`` keeps no ``Proxy``
    attribute (asserted here) and never dispatches ``execute``.
    """
    doc = FreeCAD.newDocument("shelving_probe_arg")
    try:
        recorder = _Recorder()
        raw = doc.addObject("App::Part", "Probe", recorder)
        assert not hasattr(raw, "Proxy"), "three-arg App::Part kept a Proxy"
        part = cast("ProxyHolder", raw)
        part.touch()
        doc.recompute()
        return recorder.executed
    finally:
        FreeCAD.closeDocument(doc.Name)


def _python_feature_executes(type_name: str) -> bool:
    """Return whether a fresh `type_name` object with a ``_Recorder`` proxy
    receives ``execute`` on recompute. The positive control for the probe."""
    doc = FreeCAD.newDocument("shelving_probe_ctl")
    try:
        recorder = _Recorder()
        obj = cast("ProxyHolder", doc.addObject(type_name, "Probe", recorder))
        obj.touch()
        doc.recompute()
        return recorder.executed
    finally:
        FreeCAD.closeDocument(doc.Name)


def _probe_apart_execute() -> None:
    via_attr = _apart_rejects_proxy_attr()
    via_arg = _apart_ignores_proxy_arg()
    observed = via_attr or via_arg
    print(f"APART_PROXY_EXECUTE: {'yes' if observed else 'no'}")

    # Positive control: the same _Recorder proxy on a scripted App::*Python type
    # must fire on recompute. Without this, a FreeCAD that stopped dispatching
    # execute entirely would still read `observed = False` and pass, defeating
    # the probe.
    for type_name in _PYTHON_FEATURE_TYPES:
        assert _python_feature_executes(type_name), type_name

    # Locks sh-012's container choice; see the "``App::Part`` does not call a
    # Python ``Proxy.execute``" section of docs/freecadcmd-notes.md.
    assert observed == EXPECTED_APART_EXECUTE, (observed, EXPECTED_APART_EXECUTE)


def main() -> None:
    _check_labels()
    _check_catalog()
    _check_plank_shape()
    _check_plank_recompute()
    _probe_apart_execute()
    print("shelving object layer OK")


main()
