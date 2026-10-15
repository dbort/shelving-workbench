"""The QA wizard dock with FreeCAD's GUI up: one case's first step, from
its setup button to the report."""

import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtWidgets

from freecad.Shelving import qa
from freecad.Shelving.qa import dock
from freecad.Shelving.qa.registry import ACTIONS, Action


@pytest.fixture
def wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dock.QAWizard]:
    """A new wizard whose run folder is ``tmp_path``: a progress file left in
    the real temp folder would make it ask to resume, modally."""
    monkeypatch.setattr(qa, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(dock, "_open", None)
    shown = dock.show()
    yield shown
    FreeCADGui.getMainWindow().removeDockWidget(shown)
    shown.deleteLater()
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)


def test_a_recorded_step_reaches_the_report(
    wizard: dock.QAWizard, tmp_path: Path
) -> None:
    assert wizard.parent() is FreeCADGui.getMainWindow()
    wizard.open_case("editor.camera")
    label = "Create a fresh unit in a new document"
    assert wizard.action_button.text() == label
    wizard.action_button.click()
    QtWidgets.QApplication.processEvents()
    assert wizard.action_button.text() == "\u2705 Create a fresh unit in a new document"

    # A rerun that fails takes the done mark back off.
    def fails() -> None:
        raise RuntimeError("broken")

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(ACTIONS, "fresh_unit", Action(label=label, run=fails))
        wizard.action_button.click()
    assert wizard.action_button.text() == label
    assert wizard.action_label.text() == "The action failed: broken"
    assert FreeCAD.ActiveDocument is not None
    assert FreeCAD.ActiveDocument.getObject("ShelvingUnit") is not None

    # Appended to the widget directly: printing through FreeCAD's console
    # here deadlocks the offscreen GUI on a notification popup
    # (.claude/docs/freecad-notes.md).
    report_view = FreeCADGui.getMainWindow().findChild(
        QtWidgets.QTextEdit, "Report view"
    )
    assert isinstance(report_view, QtWidgets.QTextEdit)
    report_view.append("qa-wizard-log-marker")
    wizard.comment_edit.setPlainText("Four boards, as expected.")
    wizard.verdict_buttons["pass"].click()
    assert wizard.position_label.text() == "Step 2 of 2"
    assert wizard.back_button.text() == "Back to cases"
    wizard.verdict_buttons["skip"].click()
    assert wizard.back_button.text() == "Finish case"
    assert wizard.back_button.font().bold()
    assert wizard.back_button.isDefault()
    wizard.back_button.click()
    rows = [wizard.case_list.item(i).text() for i in range(wizard.case_list.count())]
    assert wizard.report_label.text() == ""
    assert "\u2705  The camera's turn and return" in rows

    report = json.loads(wizard.save_report())
    assert wizard.report_label.text().startswith("Saved to ")
    assert json.loads(wizard._report_path.read_text(encoding="utf-8")) == report
    assert wizard._report_path.parent == wizard._progress_path.parent == tmp_path
    (case,) = report["cases"]
    assert case["id"] == "editor.camera"
    step = case["steps"][0]
    assert step["id"] == "start"
    assert step["action"] == "fresh_unit"
    assert step["presses"] == ["done", "failed: broken"]
    assert step["verdict"] == "pass"
    assert step["comment"] == "Four boards, as expected."
    assert "qa-wizard-log-marker" in step["log"]
    assert re.fullmatch(r"[0-9a-f]{40}", report["commit"]), report["commit"]
    clipboard = QtWidgets.QApplication.clipboard()
    assert clipboard is not None and clipboard.text() == str(wizard._report_path)


def test_the_commit_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: object, **kwargs: object) -> object:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert dock._commit() == "unknown"


def test_the_saved_note_clears_when_a_case_opens(wizard: dock.QAWizard) -> None:
    wizard.save_report()
    assert wizard.report_label.text().startswith("Saved to ")
    wizard.open_case("scan.refusal")
    assert wizard.report_label.text() == ""
