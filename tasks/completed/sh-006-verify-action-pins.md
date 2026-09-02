---
id: sh-006
title: "Verify GitHub Action pins online, with a --offline escape for pixi run tests"
current_agent: user
current_phase: done
review_rejections: 2
---

# sh-006: Verify GitHub Action pins online, with a --offline escape for pixi run tests

## Summary
`tools/lint-workflows.sh` checks that every `uses:` is `owner/repo@<40-hex>
# vX.Y.Z` in shape, but nothing confirms the pinned SHA is the commit that
`vX.Y.Z` actually tags. This adds `tools/check_action_pins.py`, which resolves
each tag against the GitHub API (dereferencing annotated tags) and fails on a
SHA/comment mismatch or on any network failure. Because that is the repo's
first check that needs the network, this task also gives `pixi run tests` an
`--offline` flag: with it, network-dependent checks skip themselves; without
it, a network failure in such a check fails the run. The flag is carried to
nested checks through the `SHELVING_OFFLINE` environment variable, the
documented extension point for future network-dependent checks. The checker is
built from small injectable pieces so its behaviour is covered by fast unit
tests with no network and no mock server.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [x] User sign-off

## Must Have
- [x] `tools/check-action-pins.sh` (`#!/usr/bin/env bash`, `set -euo pipefail`,
  executable): for every `uses: <owner>/<repo>[/<path>]@<40-hex> # v<maj>.<min>.<patch>`
  line across `.github/workflows/*.yml` and `*.yaml`, resolve
  `refs/tags/v<maj>.<min>.<patch>` for `<owner>/<repo>` against
  `${GITHUB_API_URL:-https://api.github.com}`, dereference an annotated-tag
  object to its target commit, and assert that commit equals the pinned
  `<40-hex>`. Every line is checked; failures aggregate and are all reported,
  not just the first. The `<path>` segment (e.g. `github/codeql-action/upload-sarif`)
  is stripped before resolving; the tag lives on `<owner>/<repo>`.
- [x] Exactly two outcomes, no third: **verified** (tag resolved, commit equals
  the pin) or **fatal** (any of: commit differs; tag missing / HTTP 404 / any
  other 4xx; a connection failure such as `curl` exit 6/7; HTTP 403/429 rate
  limit; HTTP 5xx still failing after up to 2 short retries). There is no
  exit-0 path for a network failure. A rate-limit fatal message names
  `GH_TOKEN`/`GITHUB_TOKEN` as the fix.
- [x] `SHELVING_OFFLINE` contract, honoured by every network-dependent check:
  the value `1` enables offline mode; unset or empty disables it; **any other
  value is a usage error** (the check prints
  `<name>: SHELVING_OFFLINE must be unset or 1` to stderr and exits non-zero, so
  `SHELVING_OFFLINE=0` never silently enables offline mode). When enabled,
  `tools/check-action-pins.sh` prints `check-action-pins: skipped (SHELVING_OFFLINE)`
  to stderr and exits 0 **before making any network call**. This is the only
  skip path.
- [x] The script uses `GH_TOKEN` or `GITHUB_TOKEN` as a bearer token when set,
  for rate-limit headroom; it also runs unauthenticated (reads only public tag
  data, no scope beyond the default). The `Authorization` header is sent **only
  when the resolved API host is `api.github.com`** (or the exact
  runner-provided `GITHUB_API_URL`), never to an arbitrary override, so a
  redirected or misconfigured base cannot harvest the token.
- [x] On success the script prints `check-action-pins: verified N/N pins` to
  stdout, where N is the number of `uses:` lines found, so a reviewer and the
  test can confirm it actually ran.
- [x] Classification is by outcome, not by probing first: make the real API
  call per pin and branch on the captured HTTP status
  (`curl ... -w '%{http_code}'`, never `curl --fail`). JSON is parsed with a
  `python3 -c` one-liner (`json.load(sys.stdin)`), not `jq`.
- [x] `tests/test_check_action_pins.py` (typed, `mypy --strict`-clean, added to
  `pyproject.toml` `[tool.mypy].files`): drives `tools/check-action-pins.sh` as
  a subprocess against a local mock of the tag API (a fixture `http.server`
  bound to `127.0.0.1` on an ephemeral port, `GITHUB_API_URL` pointed at it).
  It sets an explicit environment per case (clearing `SHELVING_OFFLINE` where a
  case needs the check to run) and makes no real network call. Cases:
  matching SHA → `verified N/N`, exit 0; mismatched SHA → fatal, non-zero,
  offender named; annotated-tag dereference followed correctly; tag 404 →
  fatal; unreachable API (`GITHUB_API_URL=http://127.0.0.1:1`) → fatal;
  `SHELVING_OFFLINE=1` → the skip line, exit 0, and the mock records zero
  requests. The 5xx-retry-then-fatal path is covered here too if the mock can
  express it; otherwise it is a handoff-recorded manual check.
- [x] `tools/lint-workflows.sh` calls `tools/check-action-pins.sh` as an
  additional check after the offline `uses:` pin-format check, using the same
  run-all-then-exit-nonzero aggregation it already uses for its other checks.
  It passes no new argument: `SHELVING_OFFLINE` threads through the environment.
- [x] `tools/run-tests.sh` accepts one optional argument, `--offline`. Bare
  `tools/run-tests.sh` runs everything. `tools/run-tests.sh --offline` does
  `export SHELVING_OFFLINE=1` before running the checks. Any other argument (or
  more than one) prints a one-line usage to stderr and exits 2. It only ever
  writes the value `1`. Invoked as `pixi run tests` and
  `pixi run tests -- --offline`.
- [x] `tools/run-tests.sh`'s header comment gains one line stating that
  `--offline` sets `SHELVING_OFFLINE` so network-dependent checks skip
  themselves. No enumeration of steps (per `CLAUDE.md` § Writing style).
- [x] `.github/workflows/ci.yml`: the single `tests` job (or the `pixi run
  tests` step) gains `GITHUB_TOKEN: ${{ github.token }}` in its `env`, for
  rate-limit headroom against the shared-runner IP pool. CI runs `pixi run
  tests` with no `--offline`, so the pin check runs and a network failure fails
  the job. No new workflow permission (`contents: read` already covers reading
  other public repos' tags); triggers stay `push` + `pull_request` (never
  `pull_request_target`).
- [x] `docs/github-actions-hardening.md`: the "Pin every action to a commit
  SHA" and enforcement sections state that the pin check now also verifies,
  online, that each SHA is the commit its `# vX.Y.Z` tag names; that this runs
  in CI with `GITHUB_TOKEN` and fails the run on a network failure; and that
  `pixi run tests -- --offline` skips it for offline local work. Does not
  mention `SHELVING_OFFLINE` (that is an internal tools contract, not a
  user-facing knob).
- [x] `docs/architecture.md` "Testing and CI": documents the `SHELVING_OFFLINE`
  contract (value `1` enables, unset/empty disables, other values are an error;
  a network-dependent check reads it and skips itself when enabled;
  `pixi run tests -- --offline` sets it; without it a network failure in such a
  check fails the run) as the pattern every future network-dependent check
  follows.
- [x] `README.md` `## Tests`: one added sentence that `pixi run tests --
  --offline` skips checks that need the network. High-level; does not name
  which checks.
- [x] `pixi run tests` is green on the dev VM (which has network): its output
  contains `check-action-pins: verified N/N pins`. `pixi run tests -- --offline`
  is green and its output contains `check-action-pins: skipped (SHELVING_OFFLINE)`.
  `shellcheck tools/*.sh` (already a `run-tests.sh` step) stays clean with the
  new script.
- [x] The `2026-08-30` "Reviewing SHA-pinned workflows had no tooling behind
  it" friction-log entry is removed from `.claude/docs/friction-log.md` in the
  commit that lands this task (it closes the last residual: the SHA/tag
  correspondence check).

## Frontier Advice

STANDING OBLIGATIONS (`CLAUDE.md`): **Typed Python** applies to
`tests/test_check_action_pins.py` (new Python): precise types, no bare
`Any`/`dict`/`list`/`tuple`/`set` in signatures or public attributes,
`mypy --strict` clean, and the file added to `pyproject.toml`
`[tool.mypy].files` so the `mypy` step actually covers it. The shell scripts
(`check-action-pins.sh`, `run-tests.sh`, `lint-workflows.sh`) and the
`python3 -c` JSON one-liners inside `check-action-pins.sh` are shell, not in
scope. No other standing obligation is active.

CONTEXT: sh-008 has merged. There is one check command, `pixi run tests` →
`tools/run-tests.sh`, which calls `bash tools/lint-workflows.sh` among others
and already has a `shellcheck tools/*.sh` step. There is no `test.sh`, no
`pixi run full` / `fast` / `lint-workflows` alias, and `ci.yml` has one job.
Plan against that tree.

WHY ONLINE, NOT OFFLINE: `tools/lint-workflows.sh` is otherwise fully offline
and deterministic (`zizmor --offline`, an offline regex, a bundled JSON
schema). The SHA/tag correspondence genuinely cannot be checked without the
network. Keep `check-action-pins.sh` as its own script so the offline character
of the rest of `lint-workflows.sh` stays legible.

FATAL, NOT SOFT. The danger being guarded against: a loose "can't reach the
API" branch that also swallows a rate-limit 403 or a transient 5xx, exits 0,
and prints one quiet line nobody reads, so the check silently stops verifying
while the network is fine. This design removes the temptation entirely: there
is no exit-0 path for any network failure. 403/429 → fatal (message names
`GH_TOKEN`). 404 on the tag → fatal. 5xx → retry up to 2× with a short sleep,
then fatal. `curl` exit 6/7 → fatal. The ONLY way the check does not run is
`SHELVING_OFFLINE=1`, which is explicit, caller-set, and prints a named skip
line. The happy path prints `verified N/N`.

SHELVING_OFFLINE CONTRACT: `tools/run-tests.sh --offline` does
`export SHELVING_OFFLINE=1`. Every network-dependent check validates and reads
it as its first action:

    case "${SHELVING_OFFLINE:-}" in
      "")  ;;                                      # online
      1)   echo "<name>: skipped (SHELVING_OFFLINE)" >&2; exit 0 ;;
      *)   echo "<name>: SHELVING_OFFLINE must be unset or 1" >&2; exit 2 ;;
    esac

`check-action-pins.sh` is its sole consumer today; `docs/architecture.md`
documents it as the pattern a future network-dependent check (an integration
test hitting a real service, say) follows. `run-tests.sh` reads exactly one
optional arg; keep its arg handling minimal (`case "${1:-}"` on `--offline` /
empty / everything else → exit 2) and never write any value but `1`.

CLASSIFY BY OUTCOME, not by probing first: attempt the real API call per pin
and classify its result. Capture the status with `-w '%{http_code}'` (or
`-o /dev/null -w '%{http_code}'` for the status, then a second call for the
body); do not use `curl --fail`, which collapses these into one exit code. 200
→ compare. 404 or other 4xx → fatal. 403/429 → fatal (rate limit). 5xx → retry
then fatal. `curl` non-zero exit → fatal.

API DETAIL: `GET {base}/repos/{owner}/{repo}/git/ref/tags/{tag}` returns an
object whose `object.type` is `"tag"` for an annotated tag (most releases) or
`"commit"` for a lightweight tag. For `"tag"`, follow with
`GET {base}/repos/{owner}/{repo}/git/tags/{object.sha}` and read `.object.sha`
for the commit. For `"commit"`, `object.sha` is already the commit. `base` is
`${GITHUB_API_URL:-https://api.github.com}` so the unreachable-API path and the
test mock are reachable by pointing it elsewhere.

ACTION REFS: gather the `uses:` pins from the actual workflow files, do not
hardcode a count. Today `.github/workflows/` has seven `uses:` lines across
`ci.yml` (`step-security/harden-runner`, `actions/checkout`,
`prefix-dev/setup-pixi`) and `scorecard.yml` (`step-security/harden-runner`,
`actions/checkout`, `ossf/scorecard-action`,
`github/codeql-action/upload-sarif`). Strip the `/upload-sarif` path segment
before resolving. All current pins use full `vMAJOR.MINOR.PATCH` tags that
exist upstream.

CI TOKEN IS SAFE HERE. `${{ github.token }}` (the auto `GITHUB_TOKEN`) is added
only for rate-limit headroom (unauthenticated is 60/hr per shared runner IP;
~14 calls per run flakes under contention; authenticated is 1000/hr/repo). It
is safe because: the workflow triggers on `push` and `pull_request` only, never
`pull_request_target`; the job needs only `contents: read`; for a fork PR
GitHub issues a read-only `GITHUB_TOKEN` and withholds secrets, and a read-only
token on a public repo grants an attacker nothing beyond anonymous read; the
token expires with the job. Defence in depth: the script attaches the
`Authorization` header only when the API host is the real GitHub API, so a
redirected `GITHUB_API_URL` cannot capture it. Do not switch the trigger to
`pull_request_target` and do not grant `write` scopes.

TEST MOCK: bind `http.server` to `127.0.0.1` port 0 (ephemeral), serve canned
`repos/<owner>/<repo>/git/ref/tags/<tag>` and `git/tags/<sha>` JSON, and count
requests so the `SHELVING_OFFLINE=1` case can assert zero. The test must clear
`SHELVING_OFFLINE` from the subprocess env for every case that needs the check
to actually run (`pixi run tests -- --offline` exports it into pytest's env).
No real network; the test is safe to run in every mode.

FRICTION LOG: delete the `2026-08-30` workflow-tooling entry in the commit that
lands this. Record any NEW workaround per `CLAUDE.md`.

## Rework — post-sign-off (bash → Python)

The user rejected the branch at sign-off. Two changes; the pipeline re-runs
from `implementation`. The `## Must Have`, `## Frontier Advice`, and
`## Execution Plan` above describe the shell implementation that was built and
approved; where this section conflicts with them, this section wins. All prior
behaviour (the two-outcome contract, FATAL-NOT-SOFT, the `SHELVING_OFFLINE`
contract, the token-host guard, failure aggregation, `verified N/N` output,
the `--offline` flag, the CI token, the docs) must be preserved exactly.

**R1 — `tools/check-action-pins.sh` is too complex for bash; rewrite it as
`tools/check_action_pins.py`.**
- Python 3.12, standard library only: `urllib.request` for HTTP (no `requests`
  dependency, no `curl`, no `python3 -c` sub-shells), `json`, `re`, `pathlib`,
  `os`, `sys`. Typed to the repo standard: `mypy --strict` clean, no bare
  `Any`/`dict`/`list`/`tuple`/`set` in signatures or public attributes, added
  to `pyproject.toml` `[tool.mypy].files`.
- `git rm tools/check-action-pins.sh`. `tools/run-tests.sh` and
  `tools/lint-workflows.sh` call `python3 tools/check_action_pins.py` (or
  `python tools/check_action_pins.py`) instead of `bash tools/check-action-pins.sh`.
  It no longer matches the `shellcheck tools/*.sh` glob; `mypy` covers it now.
- Structure it as importable functions so the tests can exercise pieces
  directly, not only via subprocess:
  - `workflow_pins(dir) -> tuple[Pin, ...]` — parse `uses:` lines from
    `*.yml`/`*.yaml`, strip the `<path>` segment, return `(repo, tag, sha,
    file)` records (`Pin` = `NamedTuple` or frozen dataclass).
  - `classify_status(http_status, what) -> None | str` — 200 → ok; 403/429,
    404, other 4xx, 5xx-after-retries, connection-failure → a reason string.
    Pure, no I/O.
  - `resolve_commit(fetch, base, repo, tag) -> str` / raises — takes an
    injected `fetch(url) -> Response`-like callable so a unit test passes a
    fake returning canned `(status, json)` with NO server. Handles the
    annotated-tag second hop.
  - `offline_mode() -> bool` / raises on an illegal `SHELVING_OFFLINE` value —
    the `1` / unset-empty / else-is-error contract, checked before any network
    call.
  - `auth_headers(base, env) -> Mapping[str, str]` — returns the bearer header
    only when the host is exactly `api.github.com`; empty otherwise. Pure,
    unit-testable.
  - a `main(argv) -> int` that wires them, retries 5xx up to 2× (retry sleep
    injectable / an arg defaulting to ~1s, so a unit test sets 0 or patches
    `time.sleep`), aggregates all failures, prints `check-action-pins:
    verified N/N pins` on success.

**R2 — reevaluate the testing plan.** Replace the subprocess-against-a-mock-HTTP-server
approach with direct unit tests of the functions above (no `http.server`, no
`threading`, no `poll_interval`, no per-test 0.5s teardown):
- `workflow_pins`: sample lines including a `<path>` segment, `.yaml` vs
  `.yml`, a non-matching line; assert the parsed records and count.
- `classify_status`: each status class → the expected ok/reason.
- `resolve_commit` with a fake `fetch`: lightweight tag → commit; annotated
  tag → second hop → commit; 404 → the fatal reason; a fake that raises a
  connection error → the fatal reason.
- `offline_mode`: `SHELVING_OFFLINE` unset/empty/`1`/`0`/`"true"` → run / run /
  skip / **raise** / **raise**; assert no `fetch` is called when it raises or
  skips.
- `auth_headers`: token + `api.github.com` → header present; token +
  `127.0.0.1:8080` or any other host → **no** header; no token → no header.
- One thin end-to-end test of `main()` against a stub `fetch` covering the
  all-verified path (asserts `verified N/N` on stdout, exit 0) and an
  all-mismatch path (asserts every pin's repo+sha on stderr, exit non-zero).
- `tests/test_check_action_pins.py` is rewritten to this shape; keep it in
  `[tool.mypy].files`. The `poll_interval` fixture fix from commit `112fe25`
  becomes moot (no server) — that is fine.
- The live-network check still happens for real when `pixi run tests` runs on
  the dev VM / in CI (it prints `verified 7/7 pins`); the unit tests do not
  touch the network and run in well under a second.

**R3 — `docs/github-actions-hardening.md` "Enforcement: the workflow lint"
section restates what each of the five checks does, mirroring
`lint-workflows.sh` and each tool.** Cut the per-check "what it does"
enumeration. State only: that `lint-workflows.sh` enforces the
machine-verifiable rules from this document, that it runs as part of
`pixi run tests` (and how to run it alone), and the non-obvious conventions
that are NOT visible from the code — the `# zizmor: ignore[<rule>]` +
one-line-reason policy, the offline-vs-online split rationale, and that
`shellcheck` is a `pixi.toml` dependency because `actionlint` shells out to
it. Name the five tools in a single sentence if useful; do not give each a
paragraph. Apply the same judgement to any other doc prose that walks through
a script's steps.

**Verification (supersedes Step 10):** `pixi run tests` green on the dev VM
with `check-action-pins: verified 7/7 pins`; `pixi run tests -- --offline`
green with `check-action-pins: skipped (SHELVING_OFFLINE)`; `mypy --strict`
(via `pixi run tests`) clean over `tools/check_action_pins.py` and the
rewritten test; the pin test file runs in under a second;
`shellcheck tools/*.sh` clean (now without `check-action-pins.sh`);
`git grep -n 'check-action-pins\.sh'` returns nothing outside `tasks/`.

## Execution Plan

- [x] **Step 1** (`tools/check-action-pins.sh`): Write the online resolver +
  verifier per the Must Have, FATAL-NOT-SOFT, CLASSIFY BY OUTCOME, API DETAIL,
  and SHELVING_OFFLINE CONTRACT. Gather `uses:` pins from
  `.github/workflows/*.yml`/`*.yaml`; strip any `<path>` segment; per pin, one
  real API call classified by HTTP status into `verified` / `fatal`;
  dereference annotated tags; aggregate and report all failures; retry 5xx up
  to 2×; the `SHELVING_OFFLINE` `case` guard first; bearer token from
  `GH_TOKEN`/`GITHUB_TOKEN` only when the host is the real GitHub API; print
  `check-action-pins: verified N/N pins` on success. `chmod +x`. It matches
  `run-tests.sh`'s existing `shellcheck tools/*.sh` glob, so keep it
  shellcheck-clean.

- [x] **Step 2** (`tests/test_check_action_pins.py`, `pyproject.toml`): Add the
  typed test with the fixture `http.server` mock per TEST MOCK and the Must
  Have's case list. Add the file to `[tool.mypy].files`.

- [x] **Step 3** (`tools/lint-workflows.sh`): Add `tools/check-action-pins.sh`
  as a check after the offline pin-format check, using the same failure
  aggregation. No new argument; the environment carries `SHELVING_OFFLINE`.

- [x] **Step 4** (`tools/run-tests.sh`): Replace the no-arg guard with handling
  for one optional `--offline` arg: `--offline` → `export SHELVING_OFFLINE=1`;
  empty → run as now; anything else → one-line usage to stderr, exit 2. Add one
  header-comment line about `--offline` setting `SHELVING_OFFLINE` for
  network-dependent checks (intent only, no step list).

- [x] **Step 5** (`.github/workflows/ci.yml`): Add
  `GITHUB_TOKEN: ${{ github.token }}` to the `tests` job's `env` (or the `pixi
  run tests` step's `env`). No permission or trigger change. Confirm the job
  still runs `pixi run tests` with no `--offline`.

- [x] **Step 6** (`docs/github-actions-hardening.md`): Document the online
  SHA/tag verification in the pin-related and enforcement sections: what it
  checks, that CI runs it with `GITHUB_TOKEN` and fails on a network failure,
  and the `pixi run tests -- --offline` escape. No `SHELVING_OFFLINE` mention.

- [x] **Step 7** (`docs/architecture.md`): In "Testing and CI", add the
  `SHELVING_OFFLINE` contract as the pattern every network-dependent check
  follows, and name the action-pin check as today's sole instance.

- [x] **Step 8** (`README.md`): One sentence in `## Tests` that
  `pixi run tests -- --offline` skips checks needing the network. No specifics.

- [x] **Step 9** (`.claude/docs/friction-log.md`): Remove the `2026-08-30`
  "Reviewing SHA-pinned workflows had no tooling" entry.

- [x] **Step 10** (verification, no new files): `pixi run tests` green with
  `check-action-pins: verified N/N pins` and the new pytest case passing;
  `pixi run tests -- --offline` green with
  `check-action-pins: skipped (SHELVING_OFFLINE)` in the output;
  `mypy --strict` (via `pixi run tests`) clean over the new test;
  `shellcheck tools/*.sh` clean. Record any 5xx-retry manual check in the
  handoff if the mock could not express it.
