#!/usr/bin/env bash
#
# The Shelving Workbench check harness: the single command that gates a merge.
# Run it as `pixi run tests`; the checks below assume that environment's tools.
# `--offline` exports SHELVING_OFFLINE=1 so network-dependent checks skip
# themselves instead of failing on an unreachable service. `--smoke` is the
# quick pass for use while working: in tests/freecad_gui and
# tests/freecad_view it runs only the tests marked `smoke`
# (tests/smoke_marks.py) and every other check whole, and it stops and fails
# the run once the run passes a hard 90 s limit (tools/smoke_limit.py). The full
# run has no limit and stays the merge gate. Pass either option or both
# after `--`: `pixi run tests -- --smoke --offline`.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Arguments, not PYTEST_ADDOPTS: tests/test_collection_runs.py starts pytest
# runs of its own that inherit the environment.
marked=()
for arg in "$@"; do
	case "$arg" in
		--offline) export SHELVING_OFFLINE=1 ;;
		--smoke) marked=(-m smoke) ;;
		*)
			echo "usage: run-tests.sh [--offline] [--smoke]" >&2
			exit 2
			;;
	esac
done

# The whole smoke run, static checks included, runs under the limit.
# SHELVING_SMOKE_LIMITED marks the run the limit started, so it does not
# wrap itself again.
if [[ ${#marked[@]} -gt 0 && -z ${SHELVING_SMOKE_LIMITED:-} ]]; then
	export SHELVING_SMOKE_LIMITED=1
	exec python -m tools.smoke_limit tools/run-tests.sh "$@"
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
QT_QPA_PLATFORM=offscreen pytest tests/freecad_gui "${marked[@]}"
printf '== %s\n' tests/freecad_view
python -m tools.xvfb_run pytest tests/freecad_view "${marked[@]}"
