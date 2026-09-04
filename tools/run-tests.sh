#!/usr/bin/env bash
#
# The Shelving Workbench check harness: the single command that gates a merge.
# Run it as `pixi run tests`; the checks below assume that environment's tools.
# The lone option, `--offline` (`pixi run tests -- --offline`), exports
# SHELVING_OFFLINE=1 so network-dependent checks skip themselves instead of
# failing on an unreachable service.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "${1:-}" in
	"") ;;
	--offline) export SHELVING_OFFLINE=1 ;;
	*)
		echo "usage: run-tests.sh [--offline]" >&2
		exit 2
		;;
esac
if [ "$#" -gt 1 ]; then
	echo "usage: run-tests.sh [--offline]" >&2
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

# freecadcmd does not propagate a script's exit status (see
# docs/freecadcmd-notes.md), so the smoke script's printed OK line is the pass
# signal, not its return code. Each block prints a `== <script>` header first:
# freecadcmd's C++ banner and recompute progress interleave with the script's
# own stdout, so without a header the captured blobs are hard to tell apart.
printf '== %s\n' freecad_smoke.py
smoke_output="$(freecadcmd tools/freecad_smoke.py 2>&1)" || true
printf '%s\n' "$smoke_output"
if ! printf '%s\n' "$smoke_output" | grep -q "shelving workbench import OK"; then
	echo "ERROR: freecad_smoke.py did not report success (see output above)." >&2
	exit 1
fi

printf '== %s\n' freecad_object_smoke.py
object_smoke_output="$(freecadcmd tools/freecad_object_smoke.py 2>&1)" || true
printf '%s\n' "$object_smoke_output"
if ! printf '%s\n' "$object_smoke_output" | grep -q "shelving object layer OK"; then
	echo "ERROR: freecad_object_smoke.py did not report success (see output above)." >&2
	exit 1
fi
