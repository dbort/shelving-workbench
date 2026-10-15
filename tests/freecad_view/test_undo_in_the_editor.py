"""Undo and Redo inside Edit Unit as a user runs them: ``Std_Undo`` and
``Std_Redo``, which send their message to the active 3D view, with the
panel open, and Close through the panel's own button."""

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest

from freecad.Shelving.container import read_container
from freecad.Shelving.core.geometry import Space
from freecad.Shelving.editor.panel import EditUnitPanel
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_task_button,
    edit_unit,
    gui_step,
)
from tests.freecad_view.view import ViewDriver

_REPO = Path(__file__).resolve().parents[2]
_TIMEOUT_S = 120

_Boards = tuple[tuple[str, float, float, float, float, float, float], ...]


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


class _Labeled(Protocol):
    Label: str


def _boards(container: FreeCAD.DocumentObject) -> _Boards:
    boxes, _skipped, _record = read_container(container)
    doc = container.Document
    found: list[tuple[str, float, float, float, float, float, float]] = []
    for name in sorted(box.name for box in boxes):
        obj = cast("_BoxFeature", doc.getObject(name))
        base = obj.Placement.Base
        found.append((name, obj.Length, obj.Width, obj.Height, base.x, base.y, base.z))
    return tuple(found)


def _spaces(spaces: Mapping[str, Space]) -> list[tuple[float, ...]]:
    """Every solved space, rounded, region ids aside: a rescan mints fresh
    ones and solves from measured boards, a few ulps off."""
    return sorted(
        tuple(
            round(value_mm, 6)
            for value_mm in (
                space.origin.x_mm,
                space.origin.y_mm,
                space.origin.z_mm,
                space.size.x_mm,
                space.size.y_mm,
                space.size.z_mm,
            )
        )
        for space in spaces.values()
    )


def _shown_size_mm(panel: EditUnitPanel) -> float:
    """The size the selected opening's dimension reads."""
    measurement = panel.session.selected_measurement()
    assert measurement is not None
    editor = panel.editor
    assert editor is not None
    (label,) = [
        label
        for label in editor.overlay.labels
        if label.region_id == panel.session.selected_id
    ]
    assert float(label.text) == pytest.approx(measurement.size_mm)
    return measurement.size_mm


def _add_shelf(panel: EditUnitPanel, driver: ViewDriver) -> None:
    add_board(panel, "vertical", driver)


def test_undo_and_redo_step_one_edit_and_the_panel_follows(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    session = panel.session
    _add_shelf(panel, driver)
    lower = bay_ids(session.unit.root)[0]
    session.select(lower)
    states = []
    for size_mm in (250.0, 300.0, 350.0):
        assert session.set_size(size_mm) is None
        panel._refresh()
        states.append((size_mm, _spaces(session.spaces), _boards(unit)))
    for size_mm, spaces, boards in reversed(states[:-1]):
        gui_step("Std_Undo", driver)
        assert _spaces(session.spaces) == spaces
        assert _boards(unit) == boards
        # A rescan gives the bay a fresh id; it stays selected.
        assert _shown_size_mm(panel) == pytest.approx(size_mm)
    for size_mm, spaces, boards in states[1:]:
        gui_step("Std_Redo", driver)
        assert _spaces(session.spaces) == spaces
        assert _boards(unit) == boards
        assert _shown_size_mm(panel) == pytest.approx(size_mm)
    click_task_button("Close", driver)


def test_undo_past_the_unit_closes_the_panel_and_redo_brings_it_back(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """As Sketcher's edit mode ends when its sketch is undone: past the
    session's first edit lies the step that created the unit."""
    doc = unit.Document
    opening = _boards(unit)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    first = _boards(unit)
    gui_step("Std_Undo", driver)
    assert _boards(unit) == opening
    assert FreeCADGui.Control.activeDialog()
    gui_step("Std_Undo", driver)
    assert doc.getObject("ShelvingUnit") is None
    assert not FreeCADGui.Control.activeDialog()
    gui_step("Std_Redo", driver)
    gui_step("Std_Redo", driver)
    container = doc.getObject("ShelvingUnit")
    assert container is not None
    assert _boards(container) == first


def test_close_keeps_each_edit_as_a_step(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    before_names = list(doc.UndoNames)
    objects = len(doc.Objects)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    one_shelf = _boards(unit)
    _add_shelf(panel, driver)
    two_shelves = _boards(unit)
    click_task_button("Close", driver)
    assert not FreeCADGui.Control.activeDialog()
    assert len(doc.Objects) == objects + 2
    assert doc.UndoNames == ["Add Shelf", "Add Shelf", *before_names]
    assert _boards(unit) == two_shelves
    gui_step("Std_Undo", driver)
    assert _boards(unit) == one_shelf


def test_the_gui_redo_crash_sequence_runs_cleanly(tmp_path: Path) -> None:
    """FreeCAD's Gui Redo reads freed view providers after this sequence
    (``editor/history.py``, ``_empty_gui_list``); glibc's allocator is set
    to scribble over freed memory, so a read of it crashes."""
    result_path = tmp_path / "result.txt"
    env = dict(os.environ)
    env["MALLOC_PERTURB_"] = "165"
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.freecad_view.undo_redo_sequence",
            str(result_path),
        ],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    output = child.stdout + child.stderr
    assert child.returncode == 0, output[-4000:]
    assert result_path.read_text(encoding="utf-8") == "done", output[-4000:]
