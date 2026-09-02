#!/usr/bin/env bash
#
# The Shelving Workbench check harness: the single command that gates a merge.
#
# Runs, in order, aborting at the first failure:
#
#   1. tools/check_lock_paths.py   - pixi.lock has no machine-specific absolute
#                                    path pins
#   2. ruff check .                - lint
#   3. ruff format --check .       - formatting
#   4. mypy                        - strict type check (see pyproject.toml)
#   5. shellcheck tools/*.sh       - lint the repo's own shell scripts
#   6. tools/vendor-core.sh --check - the vendored shelving_core copy is in sync
#   7. pytest shelving_core tests  - the unit suite
#   8. tools/lint-workflows.sh     - GitHub Actions hardening lint
#   9. freecadcmd tools/freecad_smoke.py - headless FreeCAD import smoke
#
# Step 9 greps stdout for a marker line instead of trusting an exit status:
# freecadcmd exits 0 no matter what the script does (see sh-007 and
# docs/freecadcmd-notes.md), so the printed "shelving workbench import OK" line
# is the only pass signal.
#
# Everything runs inside the pixi environment (`pixi run tests`), which supplies
# every tool including freecadcmd. Run directly only from an activated pixi
# shell.
#
set -euo pipefail

# The script lives in tools/; every check below runs from the repo root.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "$#" -ne 0 ]; then
	echo "usage: run-tests.sh (no arguments)" >&2
	exit 2
fi

# The only tool with a heavy external dependency; the pixi environment
# guarantees the rest.
if ! command -v freecadcmd >/dev/null 2>&1; then
	echo "ERROR: freecadcmd is not on PATH; run the checks with \`pixi run tests\`." >&2
	exit 1
fi

python3 tools/check_lock_paths.py
ruff check .
ruff format --check .
mypy
shellcheck tools/*.sh
bash tools/vendor-core.sh --check
pytest shelving_core tests
bash tools/lint-workflows.sh

# freecadcmd does not propagate a script's exit status, so the smoke script's
# printed OK line is the pass signal, not its return code.
smoke_output="$(freecadcmd tools/freecad_smoke.py 2>&1)" || true
printf '%s\n' "$smoke_output"
if ! printf '%s\n' "$smoke_output" | grep -q "shelving workbench import OK"; then
	echo "ERROR: freecad_smoke.py did not report success (see output above)." >&2
	exit 1
fi
