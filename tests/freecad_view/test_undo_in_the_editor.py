"""Undo and Redo inside Edit Unit as a user runs them: ``Std_Undo`` and
``Std_Redo``, which send their message to the active 3D view, with the
panel open, and OK and Cancel through the panel's own buttons."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest

from freecad.Shelving.container import read_container
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.history import (
    FLOOR_MESSAGE,
    NOT_FOLDED_MESSAGE,
    SESSION_STEP,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_view.editor import (
    click_task_button,
    edit_unit,
    gui_step,
    notification_count,
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


def _bay_ids(region: Region) -> list[str]:
    if isinstance(region, Bay):
        return [region.id]
    if not isinstance(region, Division):
        return []
    return [
        bay_id
        for item in region.items
        if not isinstance(item, Board)
        for bay_id in _bay_ids(item)
    ]


@pytest.fixture
def unit(driver: ViewDriver) -> Iterator[FreeCAD.DocumentObject]:
    """A fresh unit in the driver's document, made in one step of its own,
    with the workbench active as a toolbar click needs."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    doc.UndoMode = 1
    doc.openTransaction("Create Shelving Unit")
    container = create_unit(doc)
    doc.commitTransaction()
    doc.recompute()
    driver.pump()
    yield container
    if FreeCADGui.Control.activeDialog():
        FreeCADGui.Control.closeDialog()
        driver.pump()


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the panel shows in the Notification Area, still shown.
    Recorded at the panel, since the Notification Area does not count a
    message repeated unchanged."""
    shown: list[str] = []
    real = panel_module.report_error

    def record(message: str) -> None:
        shown.append(message)
        real(message)

    monkeypatch.setattr(panel_module, "report_error", record)
    return shown


def _shown_size_mm(panel: EditUnitPanel) -> float:
    widget = panel.size_field.quantity_widget
    assert widget is not None
    value = widget.property("rawValue")
    assert isinstance(value, float)
    return value


def _add_shelf(panel: EditUnitPanel, driver: ViewDriver) -> None:
    panel.session.select(_bay_ids(panel.session.unit.root)[0])
    # The panel enables its buttons for the selection when it refreshes.
    panel._refresh()
    panel.add_shelf_button.click()
    driver.pump()


def test_undo_and_redo_step_one_edit_and_the_panel_follows(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    session = panel.session
    _add_shelf(panel, driver)
    lower = _bay_ids(session.unit.root)[0]
    session.select(lower)
    states = []
    for size_mm in (250.0, 300.0, 350.0):
        assert session.set_size(size_mm) is None
        panel._refresh()
        states.append((size_mm, dict(session.spaces), _boards(unit)))
    for size_mm, spaces, boards in reversed(states[:-1]):
        gui_step("Std_Undo", driver)
        assert dict(session.spaces) == spaces
        assert _boards(unit) == boards
        assert session.selected_id == lower
        assert _shown_size_mm(panel) == pytest.approx(size_mm)
    for size_mm, spaces, boards in states[1:]:
        gui_step("Std_Redo", driver)
        assert dict(session.spaces) == spaces
        assert _boards(unit) == boards
        assert _shown_size_mm(panel) == pytest.approx(size_mm)
    click_task_button("Cancel", driver)


def test_undo_past_the_first_edit_says_so_and_redo_redoes_it(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, reported: list[str]
) -> None:
    opening = _boards(unit)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    first = _boards(unit)
    gui_step("Std_Undo", driver)
    assert _boards(unit) == opening
    assert reported == []
    notifications = notification_count()
    gui_step("Std_Undo", driver)
    assert _boards(unit) == opening
    assert reported == [FLOOR_MESSAGE]
    assert notification_count() == notifications + 1
    assert FreeCADGui.Control.activeDialog()
    gui_step("Std_Redo", driver)
    assert _boards(unit) == first
    click_task_button("Cancel", driver)


def test_ok_leaves_one_step_and_one_undo_takes_it_back(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    before_names = list(doc.UndoNames)
    before_boards = _boards(unit)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    _add_shelf(panel, driver)
    gui_step("Std_Undo", driver)
    final = _boards(unit)
    click_task_button("OK", driver)
    assert not FreeCADGui.Control.activeDialog()
    assert doc.UndoNames == [SESSION_STEP, *before_names]
    assert doc.RedoNames == []
    assert _boards(unit) == final
    gui_step("Std_Undo", driver)
    assert _boards(unit) == before_boards


def test_cancel_puts_the_document_back(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    before_names = list(doc.UndoNames)
    before_boards = _boards(unit)
    before_count = len(doc.Objects)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    _add_shelf(panel, driver)
    gui_step("Std_Undo", driver)
    click_task_button("Cancel", driver)
    assert _boards(unit) == before_boards
    assert len(doc.Objects) == before_count
    assert doc.UndoNames == before_names
    assert doc.RedoNames == []


def test_near_the_history_limit_undo_steps_one_edit_down_to_the_fold(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, reported: list[str]
) -> None:
    """FreeCAD's history holds 20 steps by default; with ten unrelated ones
    in it, a session of 30 edits folds its oldest into its floor."""
    doc = unit.Document
    elsewhere = cast("_Labeled", doc.addObject("Part::Box", "Elsewhere"))
    for number in range(10):
        doc.openTransaction("Relabel")
        elsewhere.Label = f"before the session {number}"
        doc.commitTransaction()
    before_boards = _boards(unit)
    panel = edit_unit(unit, driver)
    session = panel.session
    _add_shelf(panel, driver)
    session.select(_bay_ids(session.unit.root)[0])
    sizes_mm = [200.0 + number for number in range(29)]
    for size_mm in sizes_mm:
        assert session.set_size(size_mm) is None
    panel._refresh()
    held = 0
    for size_mm in reversed(sizes_mm[:-1]):
        shown_mm = _shown_size_mm(panel)
        gui_step("Std_Undo", driver)
        if reported:
            assert _shown_size_mm(panel) == pytest.approx(shown_mm)
            break
        assert _shown_size_mm(panel) == pytest.approx(size_mm), held
        held += 1
    assert reported == [FLOOR_MESSAGE]
    assert held >= 9
    floor_boards = _boards(unit)
    gui_step("Std_Undo", driver)
    assert _boards(unit) == floor_boards
    assert reported == [FLOOR_MESSAGE, FLOOR_MESSAGE]
    click_task_button("Cancel", driver)
    assert _boards(unit) == before_boards


@pytest.mark.parametrize("button", ["OK", "Cancel"])
def test_a_change_made_elsewhere_is_kept_and_reported(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    reported: list[str],
    button: str,
) -> None:
    doc = unit.Document
    elsewhere = cast("_Labeled", doc.addObject("Part::Box", "Elsewhere"))
    before_boards = _boards(unit)
    panel = edit_unit(unit, driver)
    _add_shelf(panel, driver)
    doc.openTransaction("Relabel")
    elsewhere.Label = "changed during the session"
    doc.commitTransaction()
    driver.pump()
    _add_shelf(panel, driver)
    final_boards = _boards(unit)
    click_task_button(button, driver)
    assert _boards(unit) == (final_boards if button == "OK" else before_boards)
    assert elsewhere.Label == "changed during the session"
    assert reported == [NOT_FOLDED_MESSAGE]


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
