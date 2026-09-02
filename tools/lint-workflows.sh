#!/usr/bin/env bash
#
# Lint the GitHub Actions workflows against this repo's hardening standard.
#
# One invocation, five fatal checks (see docs/github-actions-hardening.md):
#
#   1. actionlint over .github/workflows/       - schema + `run:` shellcheck
#   2. zizmor --offline over .github/workflows/ - Actions security audit
#   3. an offline pin-format check              - every `uses:` is
#                                                 owner/repo@<40-hex> # vX.Y.Z
#   4. check-jsonschema vendor.dependabot       - .github/dependabot.yml schema
#   5. check-action-pins.sh                     - each pinned SHA is the commit
#                                                 its `# vX.Y.Z` tag names
#
# Checks 1-4 run offline and take no GitHub token; check 5 calls the GitHub API
# and is fatal on a network failure unless SHELVING_OFFLINE=1 (set by
# `pixi run tests -- --offline`) makes it skip itself. All five run every time;
# the script exits non-zero if any of them fails.
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

# 3. Offline pin-format check. Kept as a shell function so it runs with no
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
run_check "action pin SHAs" bash tools/check-action-pins.sh

if [ "$status" -ne 0 ]; then
	echo "workflow lint: FAILED" >&2
	exit 1
fi
echo "workflow lint: OK"
