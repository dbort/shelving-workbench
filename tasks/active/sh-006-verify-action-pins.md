---
id: sh-006
title: "Verify GitHub Action pins match their version comments"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-006: Verify GitHub Action pins match their version comments

## Summary
`tools/lint-workflows.sh` checks that every `uses:` is `owner/repo@<40-hex>
# vX.Y.Z` in shape, but nothing confirms the pinned SHA is actually the commit
that `vX.Y.Z` tag points at. This adds an online check (GitHub API, annotated
tags dereferenced) that fails on a SHA/comment mismatch, wired into the workflow
lint and CI.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `tools/check-action-pins.sh` (`set -euo pipefail`): for every `uses: <owner>/<repo>[/<path>]@<40-hex> # v<maj>.<min>.<patch>` line across `.github/workflows/*.yml` and `*.yaml`, resolve `refs/tags/v<maj>.<min>.<patch>` for `<owner>/<repo>` against `${GITHUB_API_URL:-https://api.github.com}`, dereference an annotated-tag object to its target commit, and assert that commit equals the pinned `<40-hex>`. Every line is checked; failures aggregate (report all, not just the first).
- [ ] The script uses `GH_TOKEN` or `GITHUB_TOKEN` as a bearer token when set (for rate limits); it works unauthenticated too. It reads only public tag data, so no token scope beyond the default is needed.
- [ ] The script classifies each pin into exactly one of three outcomes and does not conflate them:
  - **verified** — the tag resolved and its commit equals the pinned SHA.
  - **mismatch** — the tag resolved to a different commit, OR the tag does not exist (HTTP 404), OR any other non-transient HTTP 4xx. Always fatal, in every mode.
  - **unverified** — a genuine connection failure (`curl` exit 6/7, DNS/connect), a rate-limit response (HTTP 403/429), or repeated HTTP 5xx after a small retry. Fatal in strict mode (below); otherwise the script still exits 0.
- [ ] On success the script prints `check-action-pins: verified N/N pins` (N = the number of `uses:` lines found). On any `unverified` pin outside strict mode it prints, to stderr, `check-action-pins: <k> of <N> pins UNVERIFIED (<reason>); set GH_TOKEN or run with network` — naming the count, never a bare "skipped".
- [ ] Strict mode is on when `CI` or `GITHUB_ACTIONS` is set in the environment, or `CHECK_ACTION_PINS_STRICT=1` is set explicitly. In strict mode there is no exit-0 path for an `unverified` pin: an unreachable API, a rate limit, or a 5xx fails the run. The exit-0-with-notice path exists only for an offline local run with strict mode off.
- [ ] `tools/lint-workflows.sh` calls `tools/check-action-pins.sh` as an additional check after the offline `uses:` pin-format check, with the same run-all-then-exit-nonzero aggregation the script already uses for its other checks.
- [ ] `.github/workflows/ci.yml`: the step that runs the workflow lint (currently the `full` job via `./test.sh --full`) has `GITHUB_TOKEN` (`${{ github.token }}`) in its `env`. `GITHUB_ACTIONS` is already set by the runner, so strict mode is automatically on in CI and a skip there is impossible. No new workflow permission is required (`contents: read` is enough to read other public repos' tags).
- [ ] `docs/github-actions-hardening.md`: the "Pin every action to a commit SHA" and "Enforcement" sections state that the pin check now also verifies, online, that each SHA is the commit its `# vX.Y.Z` tag names, and that this runs in CI with `GITHUB_TOKEN`.
- [ ] `shellcheck tools/check-action-pins.sh` is clean (the workflow lint runs `actionlint` which invokes `shellcheck`; the new script must also pass a direct `shellcheck`).
- [ ] `pixi run lint-workflows` exits 0 against this repo's own workflows (the dev VM has network, so the online check runs and prints `verified N/N`, N = the `uses:`-line count). `pixi run full` green. `./test.sh --fast` is unaffected.
- [ ] Verified behaviors (as `test.sh`-independent shell checks the implementer runs and records in the handoff, not necessarily committed tests): (a) a deliberately wrong pinned SHA -> `mismatch`, non-zero exit, offender named; (b) `GITHUB_API_URL` pointed at a dead address with `CHECK_ACTION_PINS_STRICT=1` -> non-zero exit (strict mode never skips); (c) same dead address with strict mode off -> exit 0 with the `<k> of <N> pins UNVERIFIED` stderr line.
- [ ] The `2026-08-30` "Reviewing SHA-pinned workflows had no tooling behind it" friction-log entry is removed from `.claude/docs/friction-log.md` (this task closes the last residual: the SHA/tag correspondence check).

## Frontier Advice

STANDING OBLIGATIONS (`CLAUDE.md`): **Typed Python** does not apply (this is
shell). No other standing obligation is active.

WHY ONLINE, NOT OFFLINE: `tools/lint-workflows.sh` is otherwise fully offline
and deterministic (`zizmor --offline`, an offline regex). The SHA/tag
correspondence genuinely cannot be checked without the network, so this one
check reaches the API. Keep `check-action-pins.sh` as its own script so the
offline character of the rest of `lint-workflows.sh` stays legible.

DO NOT let the skip become the silent default. The danger being guarded
against: a loose "can't reach the API" branch that also swallows a rate-limit
403 or a transient 5xx, exits 0, and prints one quiet line nobody reads, so the
check stops verifying while the network is fine. Countermeasures, all required:
strict mode (CI, always on there) has no exit-0 path for `unverified`; a 403 or
429 is `unverified` with a "set GH_TOKEN" message, never treated as success; a
404 on the tag is a `mismatch` (fatal); the non-strict skip line names the
count of unverified pins, not a bare "skipped"; and the happy path prints
`verified N/N` so a reviewer and a test can confirm it actually ran.

CLASSIFY BY OUTCOME, not by probing first: attempt the real API call per pin
and classify its result. `curl` exit 6/7 -> connection failure (`unverified`).
HTTP 200 -> compare. HTTP 404 -> `mismatch` (tag gone). HTTP 403/429 ->
`unverified` (rate limit; recommend a token). HTTP 5xx -> retry up to 2 times
with a short sleep, then `unverified`. Any other 4xx -> `mismatch`. Do not use
`curl --fail` (it collapses these into one exit code); capture the HTTP status
with `-w '%{http_code}'` (or `-o /dev/null -w` for the status, then a second
call for the body) and branch on it.

API DETAIL: `GET {base}/repos/{owner}/{repo}/git/ref/tags/{tag}` returns an
object whose `object.type` is `"tag"` for an annotated tag (most releases) or
`"commit"` for a lightweight tag. For `"tag"`, follow with `GET
{base}/repos/{owner}/{repo}/git/tags/{object.sha}` and read `.object.sha` for
the commit. For `"commit"`, `object.sha` is already the commit. Parse JSON with
a `python -c` one-liner (`json.load(sys.stdin)`), not `jq` (not guaranteed
present). `base` is `${GITHUB_API_URL:-https://api.github.com}` so the
unreachable-API path is testable by pointing it at a dead address.

ACTION REFS TO HANDLE: `actions/checkout`, `actions/setup-python`,
`prefix-dev/setup-pixi`, `step-security/harden-runner`, `ossf/scorecard-action`,
`github/codeql-action/upload-sarif` (strip the `/upload-sarif` path segment;
the tag lives on `github/codeql-action`). All current pins use full
`vMAJOR.MINOR.PATCH` tags that exist upstream.

`test.sh --fast` is untouched; this rides the `--full` / `pixi run
lint-workflows` path exactly as the existing workflow lint does.

FRICTION LOG: delete the `2026-08-30` workflow-tooling entry in the commit that
lands this. Record any NEW workaround per `CLAUDE.md`.

## Execution Plan

- [ ] **Step 1** (`tools/check-action-pins.sh`): Write the online resolver + verifier per the Must Have, CLASSIFY BY OUTCOME, and API DETAIL: gather `uses:` pins from `.github/workflows/*.yml`/`*.yaml`; per pin, one real API call classified into `verified` / `mismatch` / `unverified` by HTTP status (`-w '%{http_code}'`, not `--fail`); dereference annotated tags; aggregate; `mismatch` is always fatal; `unverified` is fatal in strict mode (`CI` / `GITHUB_ACTIONS` / `CHECK_ACTION_PINS_STRICT=1`) and exit-0-with-a-counted-stderr-notice otherwise; print `verified N/N` on success. `chmod +x`, `shellcheck`-clean.

- [ ] **Step 2** (`tools/lint-workflows.sh`): Add `tools/check-action-pins.sh` as a check after the offline pin-format check, using the same failure aggregation.

- [ ] **Step 3** (`.github/workflows/ci.yml`): Ensure the workflow-lint step in the `full` job has `GITHUB_TOKEN` (`${{ github.token }}`) in its `env`. The runner already sets `GITHUB_ACTIONS`, so strict mode is on in CI without any extra flag; a skip there fails the job. No permission changes.

- [ ] **Step 4** (`docs/github-actions-hardening.md`): Document the online SHA/tag verification in the pin-related sections.

- [ ] **Step 5** (`.claude/docs/friction-log.md`): Remove the `2026-08-30` "Reviewing SHA-pinned workflows had no tooling" entry.

- [ ] **Step 6** (verification, no new files): `pixi run lint-workflows` green with `verified N/N` in the output; `pixi run full` green; `shellcheck tools/check-action-pins.sh tools/lint-workflows.sh` clean; `./test.sh --fast` unaffected. Run the three negative checks from the Must Have and record the outputs in the handoff: (a) a corrupted pinned SHA -> `mismatch` fatal, offender named, then revert; (b) `GITHUB_API_URL=http://127.0.0.1:1 CHECK_ACTION_PINS_STRICT=1 tools/check-action-pins.sh` -> non-zero (strict never skips); (c) `GITHUB_API_URL=http://127.0.0.1:1 tools/check-action-pins.sh` (strict off) -> exit 0 with the `<k> of <N> pins UNVERIFIED` stderr line.
