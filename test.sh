#!/usr/bin/env bash
#
# Two-tier test harness for the Shelving Workbench.
#
#   ./test.sh --fast    lint, type-check, vendor-drift check, pytest. No FreeCAD.
#   ./test.sh --full     headless freecadcmd import smoke test. Requires FreeCAD 1.0+.
#
# The full tier hard-fails when freecadcmd is absent; it does not skip.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

usage() {
	echo "usage: test.sh --fast | --full" >&2
	exit 2
}

[ "$#" -eq 1 ] || usage

case "$1" in
--fast)
	ruff check .
	ruff format --check .
	mypy
	bash tools/vendor-core.sh --check
	pytest shelving_core
	;;
--full)
	if ! command -v freecadcmd >/dev/null 2>&1; then
		echo "ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for the full test tier; see README.md." >&2
		exit 1
	fi
	freecadcmd tools/freecad_smoke.py
	;;
*)
	usage
	;;
esac
