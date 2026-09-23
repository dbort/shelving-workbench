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
pytest freecad/Shelving/core tests
bash tools/lint-workflows.sh

# freecad_scan_smoke.py is a real pytest module that calls sys.exit on its
# own pass/fail status (docs/freecadcmd-notes.md), so its exit code is
# trustworthy; no output-grepping needed. The header line separates it
# from the checks above: freecadcmd's C++ banner and recompute progress
# interleave with the script's own stdout, so without a header the
# captured blobs are hard to tell apart.
printf '== %s\n' freecad_scan_smoke.py
scan_smoke_status=0
freecadcmd tools/freecad_scan_smoke.py || scan_smoke_status=$?
# The recompute progress bar's last write ends in a bare carriage return
# with no newline (docs/freecadcmd-notes.md), so without this, whatever
# prints next lands on the same line. Unconditional and before the status
# check, so the failure message below never inherits it either.
printf '\n'
if [ "$scan_smoke_status" -ne 0 ]; then
	echo "ERROR: freecad_scan_smoke.py failed (see output above)." >&2
	exit 1
fi

printf '== %s\n' freecad_write_smoke.py
write_smoke_status=0
freecadcmd tools/freecad_write_smoke.py || write_smoke_status=$?
printf '\n'
if [ "$write_smoke_status" -ne 0 ]; then
	echo "ERROR: freecad_write_smoke.py failed (see output above)." >&2
	exit 1
fi

# freecad_catalog_smoke.py is a straight-line script, not a pytest module
# like the two smokes above, so it signals success with a printed marker
# line rather than a trustworthy sys.exit status (docs/freecadcmd-notes.md
# explains why freecadcmd itself cannot be trusted for that on an
# assert-and-marker script).
printf '== %s\n' freecad_catalog_smoke.py
catalog_smoke_output="$(freecadcmd tools/freecad_catalog_smoke.py 2>&1)" || true
printf '%s\n' "$catalog_smoke_output"
if ! printf '%s\n' "$catalog_smoke_output" | grep -q "shelving catalog OK"; then
	echo "ERROR: freecad_catalog_smoke.py did not report success (see output above)." >&2
	exit 1
fi
