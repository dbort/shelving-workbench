#!/usr/bin/env bash
#
# Two-tier test harness for the Shelving Workbench.
#
#   ./test.sh --fast    toolchain preflight, lint, type-check, vendor-drift
#                       check, pytest. No FreeCAD.
#   ./test.sh --full    run everything: the entire --fast sequence, then the
#                       workflow-hardening lint (tools/lint-workflows.sh), then
#                       the headless freecadcmd import smoke test. A strict
#                       superset of --fast; requires FreeCAD 1.0+ and the
#                       workflow-lint toolchain.
#
# --full aborts at the first failure, so a lint/type/test regression or a bad
# workflow file fails before FreeCAD is touched. The full tier hard-fails when
# freecadcmd is absent; it does not skip.
#
# Exit status: 2 is reserved for usage errors, 3 for a failed preflight (a
# required tool is missing). Any other non-zero status is the underlying
# lint/type/test tool's own.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

usage() {
	echo "usage: test.sh --fast | --full" >&2
	exit 2
}

# Verify a tier's tools are on PATH before running any of them, so a missing
# dev environment produces one clear message instead of a bare "command not
# found" partway through.
preflight() {
	local missing=()
	local tool
	for tool in "$@"; do
		command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
	done
	if [ "${#missing[@]}" -ne 0 ]; then
		echo "ERROR: these tools must be on PATH: ${missing[*]}" >&2
		echo "Run tools/install-deps.sh, then activate the environment with" >&2
		echo "  source .venv/bin/activate   (or: pixi shell)" >&2
		exit 3
	fi
}

# The fast-tier sequence, factored out so --full can run it verbatim as its
# first stage.
run_fast() {
	ruff check .
	ruff format --check .
	mypy
	bash tools/vendor-core.sh --check
	pytest shelving_core tests
}

[ "$#" -eq 1 ] || usage

case "$1" in
--fast)
	# rsync is listed because tools/vendor-core.sh --check shells out to it;
	# a host without rsync should get the named-tool message, not a bare 127.
	preflight ruff mypy pytest rsync
	run_fast
	;;
--full)
	# --full invokes every fast-tier tool plus the workflow-lint toolchain;
	# preflight for all of them up front.
	preflight ruff mypy pytest rsync actionlint zizmor check-jsonschema shellcheck
	run_fast
	bash tools/lint-workflows.sh
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
