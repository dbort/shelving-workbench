#!/usr/bin/env bash
#
# Two-tier test harness for the Shelving Workbench.
#
#   ./test.sh --fast    toolchain preflight, lint, type-check, vendor-drift
#                       check, pytest. No FreeCAD.
#   ./test.sh --full    headless freecadcmd import smoke test. Requires
#                       FreeCAD 1.0+.
#
# The full tier hard-fails when freecadcmd is absent; it does not skip.
#
# Exit status: 2 is reserved for usage errors, 3 for a failed fast-tier
# preflight (a required dev tool is missing). Any other non-zero status is the
# underlying lint/type/test tool's own.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

usage() {
	echo "usage: test.sh --fast | --full" >&2
	exit 2
}

# Verify the fast tier's tools are importable before running any of them, so a
# missing dev environment produces one clear message instead of a bare
# "command not found" partway through.
preflight_fast() {
	local missing=()
	local tool
	for tool in ruff mypy pytest; do
		command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
	done
	if [ "${#missing[@]}" -ne 0 ]; then
		echo "ERROR: fast tier requires these tools on PATH: ${missing[*]}" >&2
		echo "Run tools/install-deps.sh, then activate the environment with" >&2
		echo "  source .venv/bin/activate   (or: pixi shell)" >&2
		exit 3
	fi
}

[ "$#" -eq 1 ] || usage

case "$1" in
--fast)
	preflight_fast
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
	# freecadcmd does not propagate a script's exit status, so the smoke
	# script's printed OK line is the pass signal, not its return code.
	smoke_output="$(freecadcmd tools/freecad_smoke.py 2>&1)" || true
	printf '%s\n' "$smoke_output"
	if ! printf '%s\n' "$smoke_output" | grep -q "shelving workbench import OK"; then
		echo "ERROR: freecad_smoke.py did not report success (see output above)." >&2
		exit 1
	fi
	;;
*)
	usage
	;;
esac
