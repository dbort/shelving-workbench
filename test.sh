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
# Exit status: 2 is reserved for usage errors, 3 for a failed preflight: a
# required tool is missing from PATH, or the active environment is out of sync
# with pyproject.toml's [dev] extra. A machine-specific pixi.lock, one that pins
# a package by absolute path, fails with status 1 from tools/check_lock_paths.py.
# Any other non-zero status is the underlying lint/type/test tool's own.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT

# Tools that must be on PATH for --fast.
readonly FAST_TOOLS=(
	# Keep sorted.
	mypy
	pytest
	python3 # Runs the dev-extra and lock-path preflight helpers.
	rsync # Used by tools/vendor-core.sh --check.
	ruff
)

# Tools that must be on PATH for --full.
readonly FULL_TOOLS=(
	"${FAST_TOOLS[@]}"
	# Keep sorted.
	actionlint
	check-jsonschema
	freecadcmd
	shellcheck
	zizmor
)

usage() {
	echo "usage: test.sh --fast | --full" >&2
	exit 2
}

# Verify a tier's tools are on PATH before running any of them, so a missing
# dev environment produces one clear message instead of a bare "command not
# found" partway through.
ensure_on_path() {
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

# Confirm every distribution named in pyproject.toml's
# [project.optional-dependencies].dev is present in the active environment. A
# .venv provisioned before a dependency was added to the extra still imports
# fine for unrelated code, so without this check a stale env first surfaces as a
# pytest collection error deep in the run instead of one actionable message.
# The helper does metadata lookup only: no import side effects, no network, and
# it exits 3 (the missing-tool code) with a fixed message when a name is absent.
preflight_dev_extra() {
	python3 tools/check_dev_extra.py
}

# Guard against pixi.lock pinning the editable self-install (or anything else) by
# an absolute filesystem path, which resolves only on the machine that wrote the
# lock and breaks CI's frozen install. Catches a regression on the next
# pixi install rather than in CI.
preflight_lock_paths() {
	python3 tools/check_lock_paths.py
}

run_fast() {
	# Run first so a stale environment or a machine-specific lock fails before
	# ruff/mypy/pytest.
	preflight_dev_extra
	preflight_lock_paths

	ruff check .
	ruff format --check .
	mypy
	bash tools/vendor-core.sh --check
	pytest shelving_core tests
}

run_full() {
	run_fast
	bash tools/lint-workflows.sh
	# freecadcmd does not propagate a script's exit status, so the smoke
	# script's printed OK line is the pass signal, not its return code.
	smoke_output="$(freecadcmd tools/freecad_smoke.py 2>&1)" || true
	printf '%s\n' "$smoke_output"
	if ! printf '%s\n' "$smoke_output" | grep -q "shelving workbench import OK"; then
		echo "ERROR: freecad_smoke.py did not report success (see output above)." >&2
		exit 1
	fi
}

main() {
	[ "$#" -eq 1 ] || usage
	cd "$REPO_ROOT"

	case "$1" in
	--fast)
		ensure_on_path "${FAST_TOOLS[@]}"
		run_fast
		;;
	--full)
		ensure_on_path "${FULL_TOOLS[@]}"
		run_full
		;;
	*)
		usage
		;;
	esac
}

main "$@"
