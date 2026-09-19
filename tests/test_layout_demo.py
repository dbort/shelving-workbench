"""Coverage of ``tools/layout_demo.py``'s run-and-print contract.

``tools/layout_demo.py`` is a documented entry point: wired into ``README.md``
and the ``pixi run demo`` task, with the sh-003 Must Have requiring it to exit
0. Lint and ``mypy --strict`` are the only other things that touch it, so its
runtime behavior gets real coverage here instead of being re-derived by hand
each review round. A refactor of ``solve`` or of any name the demo imports
trips this test.

It runs the script as a subprocess under the current interpreter from the repo
root, the same way ``python tools/layout_demo.py`` and ``pixi run demo`` do.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "tools" / "layout_demo.py"


def test_demo_runs_and_prints_the_solved_sample() -> None:
    result = subprocess.run(
        [sys.executable, str(DEMO)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines, "demo produced no stdout"
    assert lines[0] == (
        "Unit 1200 x 300 x 1200 mm, default material 18 mm birch ply (18 mm)"
    ), lines[0]

    # The in-code catalog block: a header then one row per entry (ply18, mdf12).
    assert lines[1] == "Catalog:", lines[1]
    catalog_rows = lines[2:4]
    assert catalog_rows[0].strip().startswith("ply18")
    assert catalog_rows[1].strip().startswith("mdf12")

    boards_start = lines.index("Boards:")
    region_lines = lines[4:boards_start]
    assert region_lines, "no region lines printed"
    # Every region printed names its kind and carries a solved Space.
    for line in region_lines:
        assert any(f" {kind} " in line for kind in ("bay", "void", "division"))
        assert "origin=(" in line and "size=(" in line
    # The sample's two Voids (the shorter columns' steps) are regions, printed
    # here, but contribute no board below.
    assert sum(1 for line in region_lines if " void " in line) == 2

    total_line = next(line for line in lines if line.startswith("Total board volume:"))
    board_rows = lines[boards_start + 1 : lines.index(total_line)]
    # bottom, left_side, right_side, 2 dividers, 3 tops (one per column), and
    # the shelf inside the tallest column's body: 9 boards, none for a Void.
    assert len(board_rows) == 9
    assert sum(1 for row in board_rows if row.split()[0] == "top") == 3
    assert any(row.split()[0] == "shelf" for row in board_rows)
    assert any("12 mm MDF" in row for row in board_rows)
    assert total_line.endswith(" mm^3")
