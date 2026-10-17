#!/usr/bin/env bash
#
# The Shelving Workbench check harness: the single command that gates a merge.
# Run it as `pixi run tests`; the checks below assume that environment's tools.
# `--offline` exports SHELVING_OFFLINE=1 so network-dependent checks skip
# themselves instead of failing on an unreachable service. `--smoke` leaves
# out the tests marked `full_only` (tests/conftest.py), most of them in the
# slow 3D-view suite; the full run stays the merge gate. Pass either or both
# after `--`: `pixi run tests -- --smoke --offline`.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

for arg in "$@"; do
	case "$arg" in
		--offline) export SHELVING_OFFLINE=1 ;;
		# PYTEST_ADDOPTS reaches every pytest run below.
		--smoke) export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -m 'not full_only'" ;;
		*)
			echo "usage: run-tests.sh [--offline] [--smoke]" >&2
			exit 2
			;;
	esac
done

# The only tool with a heavy external dependency; the pixi environment
# guarantees the rest.
if ! command -v freecadcmd >/dev/null 2>&1; then
	echo "ERROR: freecadcmd is not on PATH; run the checks with \`pixi run tests\`." >&2
	exit 1
fi

python3 tools/check_lock_paths.py
ruff check .
ruff format --check .
pyrefly check
shellcheck tools/*.sh
pytest freecad/Shelving/core tests --ignore=tests/freecad --ignore=tests/freecad_gui \
	--ignore=tests/freecad_view
bash tools/lint-workflows.sh

# freecadcmd runs against throwaway XDG directories so it never touches a
# developer's real FreeCAD settings; the three pytest directories below set up
# their own the same way (tests/freecad_env.py). The v1-1 directory
# name follows FreeCAD's minor version.
freecad_dirs="$(mktemp -d)"
trap 'rm -rf "$freecad_dirs"' EXIT
mkdir -p "$freecad_dirs/config/FreeCAD/v1-1"
cp tools/freecad-test-user.cfg "$freecad_dirs/config/FreeCAD/v1-1/user.cfg"
export XDG_CONFIG_HOME="$freecad_dirs/config"
export XDG_DATA_HOME="$freecad_dirs/data"
export XDG_CACHE_HOME="$freecad_dirs/cache"

printf '== %s\n' freecadcmd_import_check.py
freecadcmd tools/freecadcmd_import_check.py

# Separate processes: a running GUI changes headless FreeCAD's behavior.
printf '== %s\n' tests/freecad
pytest tests/freecad
printf '== %s\n' tests/freecad_gui
QT_QPA_PLATFORM=offscreen pytest tests/freecad_gui
printf '== %s\n' tests/freecad_view
python -m tools.xvfb_run pytest tests/freecad_view
