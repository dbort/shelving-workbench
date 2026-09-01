"""Fast-tier coverage of ``tools/check_lock_paths.py``, the pixi.lock path guard.

The repo's editable self-install lands in ``pixi.lock`` as a path entry. pixi
0.78 can write it absolute (``- pypi: /workspace``) or repo-relative (``- pypi:
./``). An absolute pin is machine-specific and breaks CI's ``frozen`` install.
``./test.sh --fast`` runs this helper so a regression to an absolute pin fails
on the next ``pixi install`` rather than in CI. This module pins the detection
rules and checks the real committed ``pixi.lock`` stays clean.
"""

import subprocess
import sys
from pathlib import Path

from tools.check_lock_paths import absolute_location_lines, main

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "tools" / "check_lock_paths.py"
REAL_LOCK = REPO_ROOT / "pixi.lock"

RELATIVE_LOCK = """\
version: 6
environments:
  default:
    packages:
      linux-64:
      - conda: https://conda.anaconda.org/conda-forge/noarch/foo-1.0-h0_0.conda
      - pypi: ./
packages:
- pypi: ./
  name: shelving-workbench
"""

ABSOLUTE_LOCK = """\
version: 6
environments:
  default:
    packages:
      linux-64:
      - conda: https://conda.anaconda.org/conda-forge/noarch/foo-1.0-h0_0.conda
      - pypi: /workspace
packages:
- pypi: /workspace
  name: shelving-workbench
  url: file:///home/someone/shelving-workbench
"""


def test_relative_and_url_locations_are_clean() -> None:
    assert absolute_location_lines(RELATIVE_LOCK) == []


def test_absolute_and_file_uri_locations_are_flagged() -> None:
    hits = absolute_location_lines(ABSOLUTE_LOCK)
    flagged = {line for _, line in hits}
    assert "- pypi: /workspace" in flagged
    assert any("file:///home/someone" in line for _, line in hits)
    assert all(lineno > 0 for lineno, _ in hits)


def test_main_returns_1_on_absolute_lock(tmp_path: Path) -> None:
    lock = tmp_path / "pixi.lock"
    lock.write_text(ABSOLUTE_LOCK, encoding="utf-8")
    assert main([str(lock)]) == 1


def test_main_returns_0_on_relative_lock(tmp_path: Path) -> None:
    lock = tmp_path / "pixi.lock"
    lock.write_text(RELATIVE_LOCK, encoding="utf-8")
    assert main([str(lock)]) == 0


def test_committed_pixi_lock_has_no_absolute_paths() -> None:
    hits = absolute_location_lines(REAL_LOCK.read_text(encoding="utf-8"))
    assert hits == [], f"pixi.lock pins absolute paths: {hits}"


def test_cli_entrypoint_returns_1_and_prints_offenders(tmp_path: Path) -> None:
    lock = tmp_path / "pixi.lock"
    lock.write_text(ABSOLUTE_LOCK, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER), str(lock)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "absolute filesystem path" in result.stderr
    assert "/workspace" in result.stderr
