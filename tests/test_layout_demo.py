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
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "tools" / "layout_demo.py"
SVG_ROOT_TAG = "{http://www.w3.org/2000/svg}svg"


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
        "Carcass 900 x 1800 x 300 mm, default material 18 mm birch ply"
    ), lines[0]

    # The sample tree: a root HORIZONTAL split over a 3-child VERTICAL split and
    # a 2-child VERTICAL split -> 3 splits, 5 leaves, 4 dividers (1 + 2 + 1).
    kinds = [
        parts[1] for parts in (line.split() for line in lines[1:]) if len(parts) > 1
    ]
    assert kinds.count("split") == 3
    assert kinds.count("leaf") == 5
    assert kinds.count("divider") == 4


def test_demo_svg_flag_writes_a_parseable_svg(tmp_path: Path) -> None:
    out = tmp_path / "layout.svg"
    result = subprocess.run(
        [sys.executable, str(DEMO), "--svg", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"wrote {out}" in result.stdout
    # The text dump still prints; --svg only adds the file and its confirmation.
    assert result.stdout.splitlines()[0] == (
        "Carcass 900 x 1800 x 300 mm, default material 18 mm birch ply"
    )

    assert out.exists()
    contents = out.read_text(encoding="utf-8")
    assert contents.strip(), "SVG file is empty"
    assert ET.fromstring(contents).tag == SVG_ROOT_TAG
