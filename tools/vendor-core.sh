#!/usr/bin/env bash
#
# Sync the vendored copy of shelving_core used by the FreeCAD workbench.
#
# Source of truth is the top-level shelving_core/ package. The workbench imports
# its copy as `from freecad.shelving.vendor import shelving_core`, so that copy
# must stay byte-identical to the source, minus the test suite and bytecode
# caches.
#
#   tools/vendor-core.sh            regenerate the vendored copy in place
#   tools/vendor-core.sh --check    exit non-zero if the vendored copy is stale
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/shelving_core/"
DEST="$REPO_ROOT/freecad/shelving/vendor/shelving_core"

RSYNC_EXCLUDES=(--exclude=tests --exclude=__pycache__)

sync_into() {
	local target="$1"
	mkdir -p "$target"
	rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$SRC" "$target/"
}

case "${1:-}" in
--check)
	TMP="$(mktemp -d)"
	trap 'rm -rf "$TMP"' EXIT
	sync_into "$TMP/shelving_core"
	if ! diff -r -x __pycache__ "$DEST" "$TMP/shelving_core" >/dev/null 2>&1; then
		echo "ERROR: freecad/shelving/vendor/shelving_core/ is out of sync with shelving_core/." >&2
		echo "Run tools/vendor-core.sh and commit the result." >&2
		diff -r -x __pycache__ "$DEST" "$TMP/shelving_core" >&2 || true
		exit 1
	fi
	;;
"")
	sync_into "$DEST"
	;;
*)
	echo "usage: vendor-core.sh [--check]" >&2
	exit 2
	;;
esac
