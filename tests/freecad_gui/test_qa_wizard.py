"""The QA wizard dock with FreeCAD's GUI up: one case's first step, from
its setup button to the report."""

import json
import re
import subprocess
from collections.abc import Iterator

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtWidgets

from freecad.Shelving.qa import dock


@pytest.fixture
def wizard() -> Iterator[dock.QAWizard]:
    shown = dock.show()
    yield shown
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)


def test_a_recorded_step_reaches_the_report(wizard: dock.QAWizard) -> None:
    assert wizard.parent() is FreeCADGui.getMainWindow()
    wizard.open_case("write.moved-board-corrected")
    assert wizard.action_button.text() == "Create a fresh unit in a new document"
    wizard.action_button.click()
    QtWidgets.QApplication.processEvents()
    assert wizard.action_button.text() == "\u2705 Create a fresh unit in a new document"
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
    assert wizard.position_label.text() == "Step 2 of 3"
    assert wizard.back_button.text() == "Back to cases"
    wizard.verdict_buttons["skip"].click()
    wizard.verdict_buttons["skip"].click()
    assert wizard.back_button.text() == "Finish case"
    assert wizard.back_button.font().bold()
    wizard.back_button.click()
    rows = [wizard.case_list.item(i).text() for i in range(wizard.case_list.count())]
    assert (
        "\u2705  A board moved by hand within the joint clearance is corrected" in rows
    )

    report = json.loads(wizard.copy_report())
    (case,) = report["cases"]
    assert case["id"] == "write.moved-board-corrected"
    step = case["steps"][0]
    assert step["id"] == "start"
    assert step["verdict"] == "pass"
    assert step["comment"] == "Four boards, as expected."
    assert "qa-wizard-log-marker" in step["log"]
    assert re.fullmatch(r"[0-9a-f]{40}", report["commit"]), report["commit"]
    clipboard = QtWidgets.QApplication.clipboard()
    assert clipboard is not None and json.loads(clipboard.text()) == report


def test_the_commit_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: object, **kwargs: object) -> object:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert dock._commit() == "unknown"
