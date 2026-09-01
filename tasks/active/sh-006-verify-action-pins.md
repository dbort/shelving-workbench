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
- [ ] `tools/check-action-pins.sh` (`set -euo pipefail`): for every `uses: <owner>/<repo>[/<path>]@<40-hex> # v<maj>.<min>.<patch>` line across `.github/workflows/*.yml` and `*.yaml`, resolve `refs/tags/v<maj>.<min>.<patch>` for `<owner>/<repo>` via `https://api.github.com`, dereference an annotated-tag object to its target commit, and assert that commit equals the pinned `<40-hex>`. Every line is checked; the script exits non-zero listing every mismatch or unresolvable tag, not just the first.
- [ ] The script uses `GH_TOKEN` or `GITHUB_TOKEN` from the environment as a bearer token when set (for API rate limits); it works unauthenticated too. It reads only public tag data, so no token scope beyond the default is needed.
- [ ] Graceful degradation: when `curl` cannot reach `api.github.com` AND no token is set, the script prints `check-action-pins: skipped (no network / token for online verification)` and exits 0, so a fully offline `pixi run lint-workflows` still passes. When the API is reachable it runs and a mismatch is fatal.
- [ ] `tools/lint-workflows.sh` calls `tools/check-action-pins.sh` as an additional check after the offline `uses:` pin-format check, with the same run-all-then-exit-nonzero aggregation the script already uses for its other checks.
- [ ] `.github/workflows/ci.yml`: the job that runs the workflow lint (currently the `full` job via `./test.sh --full`) exposes `GITHUB_TOKEN` (`${{ github.token }}` / `${{ secrets.GITHUB_TOKEN }}`) in the environment of that step so `check-action-pins.sh` actually runs online in CI rather than taking the skip path. No new workflow permission is required (`contents: read` is enough for reading other public repos' tags).
- [ ] `docs/github-actions-hardening.md`: the "Pin every action to a commit SHA" and "Enforcement" sections state that the pin check now also verifies, online, that each SHA is the commit its `# vX.Y.Z` tag names, and that this runs in CI with `GITHUB_TOKEN`.
- [ ] `shellcheck tools/check-action-pins.sh` is clean (the workflow lint runs `actionlint` which invokes `shellcheck`; the new script must also pass a direct `shellcheck`).
- [ ] `pixi run lint-workflows` exits 0 against this repo's own workflows (the dev VM has network, so the online check runs and must pass — every current pin is expected to match its tag). `pixi run full` green. `./test.sh --fast` is unaffected.
- [ ] The `2026-08-30` "Reviewing SHA-pinned workflows had no tooling behind it" friction-log entry is removed from `.claude/docs/friction-log.md` (this task closes the last residual: the SHA/tag correspondence check).

## Frontier Advice

STANDING OBLIGATIONS (`CLAUDE.md`): **Typed Python** does not apply (this is
shell). No other standing obligation is active.

WHY ONLINE, NOT OFFLINE: `tools/lint-workflows.sh` is otherwise fully offline
and deterministic (`zizmor --offline`, an offline regex). The SHA/tag
correspondence genuinely cannot be checked without the network, so this one
check is allowed to reach `api.github.com`, and it degrades to a clean skip
when it cannot. Keep `check-action-pins.sh` as its own script so the offline
character of the rest of `lint-workflows.sh` is still legible.

API DETAIL: `GET /repos/{owner}/{repo}/git/ref/tags/{tag}` returns an object
whose `object.type` is `"tag"` for an annotated tag (most releases) or
`"commit"` for a lightweight tag. For `"tag"`, follow with `GET
/repos/{owner}/{repo}/git/tags/{object.sha}` and read `.object.sha` for the
commit. For `"commit"`, `object.sha` is already the commit. Parse JSON with a
tool that is definitely present in the pixi env and the base VM: prefer a
`python -c` one-liner over assuming `jq`. `set -euo pipefail` plus explicit
per-request error handling (`curl --fail --silent --show-error`); a 404 on the
tag is a hard failure ("tag v… not found for owner/repo"), a network error with
no token is the skip path.

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

- [ ] **Step 1** (`tools/check-action-pins.sh`): Write the online resolver + verifier per the Must Have and API DETAIL: gather `uses:` pins from `.github/workflows/*.yml`/`*.yaml`, resolve each tag, dereference annotated tags, compare to the pinned SHA, aggregate failures, exit non-zero on any; clean skip (exit 0 + notice) when offline and tokenless. `chmod +x`. `shellcheck`-clean.

- [ ] **Step 2** (`tools/lint-workflows.sh`): Add `tools/check-action-pins.sh` as a check after the offline pin-format check, using the same failure aggregation.

- [ ] **Step 3** (`.github/workflows/ci.yml`): Ensure the workflow-lint step in the `full` job has `GITHUB_TOKEN` in its environment so the online check runs in CI. No permission changes.

- [ ] **Step 4** (`docs/github-actions-hardening.md`): Document the online SHA/tag verification in the pin-related sections.

- [ ] **Step 5** (`.claude/docs/friction-log.md`): Remove the `2026-08-30` "Reviewing SHA-pinned workflows had no tooling" entry.

- [ ] **Step 6** (verification, no new files): `pixi run lint-workflows` green (online check runs on the dev VM and every current pin matches its tag); `pixi run full` green; `shellcheck tools/check-action-pins.sh tools/lint-workflows.sh` clean; `./test.sh --fast` unaffected. Temporarily corrupt one pinned SHA locally and confirm the check fails and names it, then revert.
