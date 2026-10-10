"""The QA wizard dock with FreeCAD's GUI up: one case's first step, from
its setup button to the report."""

import json
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
    assert FreeCAD.ActiveDocument is not None
    assert FreeCAD.ActiveDocument.getObject("ShelvingUnit") is not None

    wizard.comment_edit.setPlainText("Four boards, as expected.")
    wizard.verdict_buttons["pass"].click()
    assert wizard.position_label.text() == "Step 2 of 3"

    report = json.loads(wizard.copy_report())
    (case,) = report["cases"]
    assert case["id"] == "write.moved-board-corrected"
    (step,) = case["steps"]
    assert step["id"] == "start"
    assert step["verdict"] == "pass"
    assert step["comment"] == "Four boards, as expected."
    clipboard = QtWidgets.QApplication.clipboard()
    assert clipboard is not None and json.loads(clipboard.text()) == report
