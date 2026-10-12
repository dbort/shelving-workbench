"""The shared refusal helper and its suggestion table, headless.

``tests/freecad_gui/test_refusals.py`` covers the 3D selection and every
command's refusal path, which need FreeCAD's GUI.
"""

from typing import get_args

import FreeCAD
import pytest

from freecad.Shelving import refusals
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Unit
from freecad.Shelving.core.scan import ScanErrorReason
from freecad.Shelving.core.solver import LayoutSolveError, SolveErrorReason


def test_every_reason_has_a_suggestion() -> None:
    """Every reason a scan, a solve or a command refuses with has its own
    suggested next step, and the table holds nothing else."""
    reasons = {
        *get_args(ScanErrorReason),
        *get_args(SolveErrorReason),
        *get_args(refusals.CommandRefusalReason),
    }
    assert set(refusals.SUGGESTIONS) == reasons
    assert all(text.strip() for text in refusals.SUGGESTIONS.values())


def test_a_refusal_prints_summary_objects_and_suggestion_in_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under ``freecadcmd`` there is no 3D view to select in, so a refusal
    prints and selects nothing rather than raising. A labeled object is
    shown by its label with its name beside it."""
    doc = FreeCAD.newDocument("refusal_print")
    try:
        labeled = doc.addObject("Part::Box", "left_side")
        labeled.Label = "Side 1"
        doc.addObject("Part::Box", "Overlap")
        refusals.report_refusal(
            "Overlap overlaps left_side", ("Overlap", "left_side", "Gone"), "Fix it."
        )
    finally:
        FreeCAD.closeDocument(doc.Name)
    assert capsys.readouterr().out.splitlines() == [
        "REFUSED: Overlap overlaps left_side",
        "  Objects: Overlap, Side 1 (left_side), Gone",
        "  Next: Fix it.",
    ]


def test_a_refusal_naming_no_objects_prints_no_objects_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    refusals.report_refusal("Nothing to do.", (), "Try again.")
    assert capsys.readouterr().out.splitlines() == [
        "REFUSED: Nothing to do.",
        "  Next: Try again.",
    ]


def _unit() -> tuple[Unit, Division, Bay, Board, Board]:
    """A closed single-bay unit: the root stacks bottom, the run of sides
    and the bay, and top. Returns the unit, the run, the bay and its two
    sides."""
    left = Board(thickness_mm=18.0, role="left_side", id="left_side")
    right = Board(thickness_mm=18.0, role="right_side", id="right_side")
    bay = Bay()
    run = Division(axis=Axis.X, items=[left, bay, right])
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, role="bottom", id="bottom"),
            run,
            Board(thickness_mm=18.0, role="top", id="top"),
        ],
    )
    return Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=root), run, bay, left, right


def test_a_solve_refusal_names_the_boards_a_user_would_move() -> None:
    unit, run, bay, left, right = _unit()

    def objects(node_id: str) -> tuple[str, ...]:
        err = LayoutSolveError(node_id, "overflow", {})
        return refusals.solve_error_objects(unit, err)

    assert objects(unit.root.id) == ("bottom", "top")
    assert objects(run.id) == ("left_side", "right_side")
    assert objects(bay.id) == (left.id, right.id)
    assert objects("top") == ("top",)
    assert objects("not-in-the-unit") == ()
