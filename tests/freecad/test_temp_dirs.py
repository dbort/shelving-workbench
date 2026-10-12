"""Per-user folders under FreeCAD's temp directory, and where Export Boxes
writes."""

import getpass
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import FreeCAD
import pytest

from freecad.Shelving import temp_dirs
from freecad.Shelving.commands import export_boxes
from freecad.Shelving.unit_ops import create_unit


@pytest.fixture
def doc() -> Iterator[FreeCAD.Document]:
    document = FreeCAD.newDocument("Temp_Dirs")
    yield document
    FreeCAD.closeDocument(document.Name)


def _container(doc: FreeCAD.Document, label: str) -> FreeCAD.DocumentObject:
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    container.Label = label
    return container


def test_a_folder_is_named_for_its_purpose_and_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "dave b/ort")
    folder = temp_dirs.user_temp_dir("exports")
    assert folder.parent == Path(FreeCAD.getTempPath())
    assert folder.name == "shelving-exports-dave_b_ort"


def test_an_unsaved_documents_export_goes_to_the_exports_folder(
    doc: FreeCAD.Document,
) -> None:
    path = temp_dirs.export_path(_container(doc, "My Unit"))
    assert path.parent.parent == temp_dirs.user_temp_dir("exports")
    assert path.parent.name == "Temp_Dirs"
    assert path.name == "My_Unit.boxes.json"
    assert (
        Path.home() not in path.parents or Path(FreeCAD.getTempPath()) in path.parents
    )


def test_a_saved_documents_export_goes_there_too(
    doc: FreeCAD.Document, tmp_path: Path
) -> None:
    container = _container(doc, "Unit")
    doc.saveAs(str(tmp_path / "saved.FCStd"))
    path = temp_dirs.export_path(container)
    assert tmp_path not in path.parents
    assert path.parent.parent == temp_dirs.user_temp_dir("exports")


def test_export_boxes_writes_an_unsaved_unit_to_the_exports_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Driven headless, with the selection the command reads from the GUI
    supplied directly: a GUI selection here leaves the offscreen GUI suite
    deadlocked on a notification popup (.claude/docs/freecad-notes.md)."""
    doc = FreeCAD.newDocument("Export_Unsaved")
    try:
        container = create_unit(doc)
        doc.recompute()

        def user_temp_dir(purpose: str) -> Path:
            return tmp_path / purpose

        monkeypatch.setattr(temp_dirs, "user_temp_dir", user_temp_dir)
        monkeypatch.setattr(export_boxes, "_selected_container", lambda: container)
        export_boxes.ExportBoxesCommand().Activated()
        path = tmp_path / "exports" / "Export_Unsaved" / "ShelvingUnit.boxes.json"
        assert path.is_file()
        assert len(json.loads(path.read_text(encoding="utf-8"))["boxes"]) == 4
    finally:
        FreeCAD.closeDocument(doc.Name)
