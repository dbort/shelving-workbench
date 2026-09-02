#!/usr/bin/env bash
#
# Verify online that every SHA-pinned GitHub Action is the commit its
# `# vX.Y.Z` comment names. For each
# `uses: <owner>/<repo>[/<path>]@<40-hex> # v<maj>.<min>.<patch>` line under
# .github/workflows/, resolve `refs/tags/v<maj>.<min>.<patch>` for
# `<owner>/<repo>` against the GitHub API, dereference an annotated-tag object
# to its target commit, and assert that commit equals the pinned SHA.
#
# There are exactly two outcomes: verified (every pin resolved and matched) or
# fatal. A mismatch, a missing tag, a rate-limit response, a 5xx that persists
# after retries, and a connection failure are all fatal; there is no exit-0
# path for a network failure. The one exception is SHELVING_OFFLINE=1, which
# skips the check before any network call.
#
# Env:
#   SHELVING_OFFLINE            1 = skip (offline); unset/empty = run;
#                              any other value is a usage error.
#   GITHUB_API_URL             API base; defaults to https://api.github.com.
#   GH_TOKEN / GITHUB_TOKEN    bearer token for API quota headroom, sent only
#                              when the resolved API host is api.github.com.
#   CHECK_ACTION_PINS_RETRY_SLEEP
#                              seconds to sleep between 5xx retries (default 1);
#                              tests set 0 so the retry path does not stall.
#
set -euo pipefail

NAME="check-action-pins"

# SHELVING_OFFLINE contract, shared by every network-dependent check.
case "${SHELVING_OFFLINE:-}" in
	"") ;;
	1) echo "${NAME}: skipped (SHELVING_OFFLINE)" >&2; exit 0 ;;
	*) echo "${NAME}: SHELVING_OFFLINE must be unset or 1" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW_DIR=".github/workflows"
BASE="${GITHUB_API_URL:-https://api.github.com}"
RETRY_SLEEP="${CHECK_ACTION_PINS_RETRY_SLEEP:-1}"

api_host="${BASE#http://}"
api_host="${api_host#https://}"
api_host="${api_host%%/*}"

# Attach the token only to the real GitHub API, so a redirected or
# misconfigured GITHUB_API_URL cannot harvest it.
CURL_AUTH=()
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -n "$token" ] && [ "$api_host" = "api.github.com" ]; then
	CURL_AUTH=(-H "Authorization: Bearer ${token}")
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

RESOLVE_ERR=""

# http_get URL OUTFILE: write the response body to OUTFILE and print the final
# HTTP status to stdout ("000" for a connection-level failure). A 5xx response
# is retried up to twice with a short sleep before its status is returned.
http_get() {
	local url="$1" out="$2"
	local attempt=0 status rc
	while :; do
		rc=0
		status="$(curl -sS -m 20 "${CURL_AUTH[@]}" \
			-H 'Accept: application/vnd.github+json' \
			-o "$out" -w '%{http_code}' "$url")" || rc=$?
		if [ "$rc" -ne 0 ]; then
			echo "000"
			return 0
		fi
		case "$status" in
			5??)
				if [ "$attempt" -lt 2 ]; then
					attempt=$((attempt + 1))
					sleep "$RETRY_SLEEP"
					continue
				fi
				;;
		esac
		echo "$status"
		return 0
	done
}

# classify_status STATUS WHAT: return 0 for 200, otherwise set RESOLVE_ERR to a
# human-readable reason and return 1.
classify_status() {
	local status="$1" what="$2"
	case "$status" in
		200) return 0 ;;
		000) RESOLVE_ERR="cannot reach ${BASE} for ${what}: connection failed" ;;
		403 | 429) RESOLVE_ERR="rate limited (HTTP ${status}) for ${what}; set GH_TOKEN or GITHUB_TOKEN to raise the API quota" ;;
		404) RESOLVE_ERR="tag not found (HTTP 404) for ${what}" ;;
		5??) RESOLVE_ERR="server error (HTTP ${status}) for ${what} after retries" ;;
		*) RESOLVE_ERR="unexpected HTTP ${status} for ${what}" ;;
	esac
	return 1
}

# json_object_fields FILE: print "<object.type> <object.sha>" from the JSON in
# FILE. Both the ref payload and the tag-object payload carry an `object` with
# these two fields.
json_object_fields() {
	python3 -c 'import json, sys
d = json.load(open(sys.argv[1]))
o = d["object"]
print(o["type"], o["sha"])' "$1"
}

# resolve_commit OWNER/REPO TAG: print the commit SHA that TAG names, or set
# RESOLVE_ERR and return 1.
resolve_commit() {
	local repo="$1" tag="$2"
	local body="${WORKDIR}/ref.json" status otype osha
	status="$(http_get "${BASE}/repos/${repo}/git/ref/tags/${tag}" "$body")"
	classify_status "$status" "${repo}@${tag}" || return 1

	otype=""
	osha=""
	read -r otype osha < <(json_object_fields "$body" 2>/dev/null) || true
	if [ -z "$otype" ] || [ -z "$osha" ]; then
		RESOLVE_ERR="unexpected API response resolving ${repo} ref ${tag}"
		return 1
	fi

	if [ "$otype" = "commit" ]; then
		printf '%s\n' "$osha"
		return 0
	fi

	if [ "$otype" = "tag" ]; then
		local tbody="${WORKDIR}/tag.json" tstatus tsha
		tstatus="$(http_get "${BASE}/repos/${repo}/git/tags/${osha}" "$tbody")"
		classify_status "$tstatus" "${repo} tag object for ${tag}" || return 1
		tsha=""
		read -r _ tsha < <(json_object_fields "$tbody" 2>/dev/null) || true
		if [ -z "$tsha" ]; then
			RESOLVE_ERR="unexpected API response dereferencing ${repo} tag object for ${tag}"
			return 1
		fi
		printf '%s\n' "$tsha"
		return 0
	fi

	RESOLVE_ERR="unexpected tag object type '${otype}' for ${repo}@${tag}"
	return 1
}

# Gather the pins from the workflow files. Both `.yml` and `.yaml` are read so a
# `.yaml` workflow cannot slip past. The reference before `@` may carry extra
# path segments (github/codeql-action/upload-sarif); the tag lives on the
# leading <owner>/<repo>, so strip the rest before resolving.
pin_repo=()
pin_tag=()
pin_sha=()
pin_file=()
pin_re='^uses: ([A-Za-z0-9._/-]+)@([0-9a-f]{40}) # v([0-9]+\.[0-9]+\.[0-9]+)$'

while IFS= read -r -d '' file; do
	while IFS= read -r raw; do
		trimmed="$(printf '%s' "$raw" | sed 's/^[[:space:]]*//; s/^-[[:space:]]*//; s/[[:space:]]*$//')"
		if [[ "$trimmed" =~ $pin_re ]]; then
			pin_repo+=("$(printf '%s' "${BASH_REMATCH[1]}" | cut -d/ -f1-2)")
			pin_tag+=("v${BASH_REMATCH[3]}")
			pin_sha+=("${BASH_REMATCH[2]}")
			pin_file+=("$file")
		fi
	done < <(grep -E '^[[:space:]]*-?[[:space:]]*uses:' "$file" || true)
done < <(find "$WORKFLOW_DIR" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) -print0)

n="${#pin_sha[@]}"
if [ "$n" -eq 0 ]; then
	echo "${NAME}: found no 'uses:' pins under ${WORKFLOW_DIR}" >&2
	exit 1
fi

# Resolve every pin; collect all failures so one run reports them together.
failures=()
verified=0
i=0
while [ "$i" -lt "$n" ]; do
	repo="${pin_repo[$i]}"
	tag="${pin_tag[$i]}"
	sha="${pin_sha[$i]}"
	file="${pin_file[$i]}"
	if commit="$(resolve_commit "$repo" "$tag")"; then
		if [ "$commit" = "$sha" ]; then
			verified=$((verified + 1))
		else
			failures+=("${file}: ${repo}@${tag} is pinned at ${sha} but the tag resolves to ${commit}")
		fi
	else
		failures+=("${file}: ${repo}@${tag}: ${RESOLVE_ERR}")
	fi
	i=$((i + 1))
done

if [ "${#failures[@]}" -ne 0 ]; then
	echo "${NAME}: FAILED" >&2
	for f in "${failures[@]}"; do
		echo "  ${f}" >&2
	done
	exit 1
fi

printf '%s: verified %d/%d pins\n' "$NAME" "$verified" "$n"
