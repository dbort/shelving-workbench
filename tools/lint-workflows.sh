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

# Offline pin-format check. Kept as a shell function so it runs with no
# network and no third-party tool: every `uses:` must name a full 40-hex
# commit SHA with a trailing `# vX.Y.Z` release comment. The action reference
# before `@` may carry extra path segments (e.g. github/codeql-action/upload-sarif).
# Both `.yml` and `.yaml` are checked: actionlint and zizmor take the whole
# directory, so a `.yaml` workflow must not slip past the pin check.
check_pins() {
	local pin_regex='^uses: [A-Za-z0-9._/-]+@[0-9a-f]{40} # v[0-9]+\.[0-9]+\.[0-9]+$'
	local rc=0 file raw trimmed
	while IFS= read -r -d '' file; do
		while IFS= read -r raw; do
			# Normalise both `uses:` on its own line and `- uses:` list items.
			trimmed="$(printf '%s' "$raw" | sed 's/^[[:space:]]*//; s/^-[[:space:]]*//; s/[[:space:]]*$//')"
			if [[ ! "$trimmed" =~ $pin_regex ]]; then
				echo "  ${file}: unpinned or mis-commented: ${trimmed}" >&2
				rc=1
			fi
		done < <(grep -E '^[[:space:]]*-?[[:space:]]*uses:' "$file" || true)
	done < <(find "$WORKFLOW_DIR" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) -print0)
	return "$rc"
}

run_check "actionlint" actionlint
run_check "zizmor (offline)" zizmor --offline "$WORKFLOW_DIR"
run_check "uses: pin format" check_pins
run_check "dependabot schema" check-jsonschema --builtin-schema vendor.dependabot "$DEPENDABOT"
# Online check: SHELVING_OFFLINE threads through the environment, no new argument.
run_check "action pin SHAs" python3 tools/check_action_pins.py

if [ "$status" -ne 0 ]; then
	echo "workflow lint: FAILED" >&2
	exit 1
fi
echo "workflow lint: OK"
