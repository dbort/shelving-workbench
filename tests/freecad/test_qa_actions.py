"""The QA wizard's setup actions and checks against a real FreeCAD
document: each case's actions run in step order from a clean slate."""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import FreeCAD
import pytest

from freecad.Shelving import init_gui, qa
from freecad.Shelving.qa import actions
from freecad.Shelving.qa.model import Case, load_cases
from freecad.Shelving.qa.registry import ACTIONS, CHECKS


@pytest.fixture(autouse=True)
def no_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Saves land in ``tmp_path``, and every document an action opened is
    closed afterwards."""
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    yield
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case.id)
def test_every_action_and_check_of_a_case_runs(case: Case) -> None:
    for step in case.steps:
        if step.action is not None:
            ACTIONS[step.action].run()
        if step.check is not None:
            CHECKS[step.check](FreeCAD.ActiveDocument)


def test_side_1_check_reads_the_nudge() -> None:
    actions.fresh_unit()
    check = CHECKS["side_1_at_x_zero"]
    assert check(FreeCAD.ActiveDocument).passed
    actions.nudge_side_1()
    result = check(FreeCAD.ActiveDocument)
    assert not result.passed
    assert result.detail == "Side 1 x = 2 mm"


def test_the_saved_document_lands_where_the_message_says(tmp_path: Path) -> None:
    actions.fresh_unit()
    message = actions.save_to_temp()
    assert message == f"Saved to {tmp_path / 'QA_Unit.FCStd'}"
    assert (tmp_path / "QA_Unit.FCStd").is_file()


@pytest.mark.parametrize("enabled", [True, False])
def test_the_menu_holds_the_wizard_only_while_its_flag_is_on(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qa, "enabled", enabled)
    assert ("Shelving_QAWizard" in init_gui.menu_commands()) is enabled
    assert "Shelving_QAWizard" not in init_gui.TOOLBAR_COMMANDS


def test_the_wizard_is_on_by_default() -> None:
    assert qa.enabled is True
