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
# required tool is missing from PATH, or the active environment is out of sync
# with pyproject.toml's [dev] extra). Any other non-zero status is the
# underlying lint/type/test tool's own.
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

# Confirm every distribution named in pyproject.toml's
# [project.optional-dependencies].dev is present in the active environment. A
# .venv provisioned before a dependency was added to the extra still imports
# fine for unrelated code, so without this check a stale env first surfaces as a
# pytest collection error deep in the run instead of one actionable message.
# Metadata lookup only: no import side effects, no network.
preflight_dev_extra() {
	python3 - <<'PY'
import importlib.metadata as metadata
import re
import sys
import tomllib

with open("pyproject.toml", "rb") as handle:
    dev = tomllib.load(handle)["project"]["optional-dependencies"]["dev"]

missing = []
for spec in dev:
    # Strip any version/marker/extra suffix to leave the bare distribution name,
    # which is what importlib.metadata resolves against.
    name = re.split(r"[<>=!~;\[\s]", spec, maxsplit=1)[0].strip()
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        missing.append(name)

if missing:
    print(
        f"dev environment is out of sync with the [dev] extra: {', '.join(missing)}. "
        "Run tools/install-deps.sh.",
        file=sys.stderr,
    )
    sys.exit(3)
PY
}

# The fast-tier sequence, factored out so --full can run it verbatim as its
# first stage. The dev-extra check runs first so a stale environment fails
# before ruff/mypy/pytest are invoked.
run_fast() {
	preflight_dev_extra
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
