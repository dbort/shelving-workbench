"""The QA wizard's setup actions and checks against a real FreeCAD
document: each case's actions run in step order from a clean slate."""

import getpass
from collections.abc import Callable, Iterator
from pathlib import Path

import FreeCAD
import pytest

from freecad.Shelving import init_gui, qa
from freecad.Shelving.core.layout import Basis, Bay, Board, Division, Fixed, Region
from freecad.Shelving.editor.session import Session
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


def test_the_fresh_unit_check_passes_on_a_fresh_unit() -> None:
    actions.fresh_unit()
    result = CHECKS["fresh_unit_size"](FreeCAD.ActiveDocument)
    assert result.passed, result.detail


def test_the_two_shelf_unit_holds_one_shelf_by_spacing_and_one_by_clear() -> None:
    actions.two_shelf_unit()
    doc = FreeCAD.ActiveDocument
    assert doc is not None
    container = doc.getObject("ShelvingUnit")
    assert container is not None
    session = Session(container)
    rules = [node.rule for node in _bays(session.unit.root)]
    assert len(rules) == 3
    assert isinstance(rules[0], Fixed) and rules[0].basis is Basis.WITH_NEXT
    assert isinstance(rules[1], Fixed) and rules[1].basis is Basis.CLEAR
    assert not isinstance(rules[2], Fixed)


def _bays(region: Region) -> list[Bay]:
    if isinstance(region, Bay):
        return [region]
    if not isinstance(region, Division):
        return []
    return [
        bay
        for item in region.items
        if not isinstance(item, Board)
        for bay in _bays(item)
    ]


@pytest.mark.parametrize(
    ("setup", "names"),
    [
        ((actions.fresh_unit,), ["Create Shelving Unit"]),
        ((actions.large_unit,), ["Divide Unit", "Create Shelving Unit"]),
        ((actions.two_shelf_unit,), ["Add Shelves", "Create Shelving Unit"]),
        (
            (actions.test_unit, actions.add_overlap_box),
            ["Add Overlap", "Create TestUnit"],
        ),
        (
            (actions.shelf_unit_with_varset,),
            ["Add Shelf", "Add VarSet", "Create Shelving Unit"],
        ),
    ],
)
def test_each_setup_is_an_undo_step_of_its_own(
    setup: tuple[Callable[[], None], ...], names: list[str]
) -> None:
    """As a document made with File, New records a person's own edits."""
    for run in setup:
        run()
    doc = FreeCAD.ActiveDocument
    assert doc is not None
    assert doc.UndoNames == names


def test_the_run_folder_is_per_user_under_freecads_temp_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(getpass, "getuser", lambda: "dave b/ort")
    run_dir = qa.temp_dir()
    assert run_dir.parent == Path(FreeCAD.getTempPath())
    assert run_dir.name == "shelving-qa-dave_b_ort"
