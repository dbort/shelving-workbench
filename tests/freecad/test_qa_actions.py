"""The QA wizard's setup actions and checks against a real FreeCAD
document: each case's actions run in step order from a clean slate."""

import getpass
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
    """The run folder lands in ``tmp_path``, and every document an action
    opened is closed afterward."""
    monkeypatch.setattr(qa, "temp_dir", lambda: tmp_path)
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


@pytest.mark.parametrize("enabled", [True, False])
def test_the_menu_holds_the_wizard_only_while_its_flag_is_on(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qa, "enabled", enabled)
    assert ("Shelving_QAWizard" in init_gui.menu_commands()) is enabled
    assert "Shelving_QAWizard" not in init_gui.TOOLBAR_COMMANDS


def test_the_wizard_is_on_by_default() -> None:
    assert qa.enabled is True


def test_the_fresh_unit_checks_pass_on_a_fresh_unit() -> None:
    actions.fresh_unit()
    for name in ("four_boards", "fresh_unit_size"):
        result = CHECKS[name](FreeCAD.ActiveDocument)
        assert result.passed, (name, result.detail)


def test_the_run_folder_is_per_user_under_freecads_temp_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(getpass, "getuser", lambda: "dave b/ort")
    run_dir = qa.temp_dir()
    assert run_dir.parent == Path(FreeCAD.getTempPath())
    assert run_dir.name == "shelving-qa-dave_b_ort"
