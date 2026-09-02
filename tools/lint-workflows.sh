#!/usr/bin/env bash
#
# Lint the GitHub Actions workflows against this repo's hardening standard
# (see docs/github-actions-hardening.md). One invocation runs every check and
# exits non-zero if any of them fails.
#
# All but one check run offline and need no GitHub token. The exception
# resolves each pinned SHA against the GitHub API and is fatal on a network
# failure, unless SHELVING_OFFLINE=1 (set by `pixi run tests -- --offline`)
# makes it skip itself before the first request.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW_DIR=".github/workflows"
DEPENDABOT=".github/dependabot.yml"
ZIZMOR_CONFIG="zizmor.yml"

status=0

run_check() {
	local label="$1"
	shift
	echo "== ${label}"
	if ! "$@"; then
		echo "FAIL: ${label}" >&2
		status=1
	fi
}

# zizmor's unpinned-uses audit enforces the full 40-hex SHA pin. `--config` is
# passed explicitly rather than relying on CWD discovery, so a missing or
# unreadable zizmor.yml is a hard error instead of a silent fall-back to
# zizmor's built-in default (which happens to match, hiding the breakage).
# check_action_pins.py checks the trailing `# vX.Y.Z` comment beside each SHA,
# offline before its network calls, so a missing or malformed comment fails
# even under --offline.
run_check "actionlint" actionlint
run_check "zizmor (offline)" zizmor --offline --config "$ZIZMOR_CONFIG" "$WORKFLOW_DIR"
run_check "dependabot schema" check-jsonschema --builtin-schema vendor.dependabot "$DEPENDABOT"
# Online check: SHELVING_OFFLINE threads through the environment, no new argument.
run_check "action pin SHAs" python3 tools/check_action_pins.py

if [ "$status" -ne 0 ]; then
	echo "workflow lint: FAILED" >&2
	exit 1
fi
echo "workflow lint: OK"
