"""Edit Unit: one editing session over a unit, worked in FreeCAD's 3D view
with a slim task panel beside it.

``elevation.py`` imports neither FreeCAD nor Qt and is tested under plain
pytest; ``session.py`` and ``history.py`` run under ``freecadcmd``. The
in-view editor needs a real 3D view, which only the Xvfb tier has, so
every decision worth testing without one lives in ``elevation.py`` or the
session.
"""
