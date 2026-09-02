# sh-006 Review — Round 1

**Verdict:** REJECTED

Both check runs are green on this branch: `pixi run tests` prints
`check-action-pins: verified 7/7 pins` and `pixi run tests -- --offline` prints
`check-action-pins: skipped (SHELVING_OFFLINE)`, with all 70 pytest cases
(including the 7 new ones) passing in both modes. The script, the workflow-lint
wiring, the CI token, and the four doc edits all match the Must Have. What is
missing is automated coverage for the two guards that exist precisely to stop
this check from silently degrading. Both are enforced correctly in the script
today and both are invisible to the committed test, so a later refactor that
removes either one leaves every test green.

## Blocking findings

- **F1: the `SHELVING_OFFLINE` value guard has no committed test**
  (`tools/check-action-pins.sh:31-35`, `tests/test_check_action_pins.py:171-187`):
  the `case` guard is correct and is the script's first action, and
  `SHELVING_OFFLINE=0` does fall to `*)` and exit 2. But
  `tests/test_check_action_pins.py` only exercises the `1` branch
  (`test_offline_skips_before_any_network_call`) and the unset branch (every
  other case, via the `_run` env filter). Nothing pins the third branch. The
  Must Have singles this behaviour out in bold, naming `SHELVING_OFFLINE=0` as
  the value that must never silently enable offline mode; that is the exact
  silent-skip regression the task's FATAL-NOT-SOFT section exists to prevent,
  and it is currently guarded only by reading the source. Add a case that runs
  the script with `SHELVING_OFFLINE=0`, asserts a non-zero exit, asserts the
  `check-action-pins: SHELVING_OFFLINE must be unset or 1` line on stderr, and
  asserts the mock recorded zero requests (proving the guard fires before any
  network call, not just that the run failed).

- **F2: the token-host guard is untestable by construction in the current test**
  (`tools/check-action-pins.sh:50-53`, `tests/test_check_action_pins.py:174-176`):
  the script attaches `Authorization: Bearer` only when `api_host` is exactly
  `api.github.com`, which is right, and it fails closed on the userinfo and
  case-variant forms as well. The test cannot observe this: `_run` strips
  `GH_TOKEN` and `GITHUB_TOKEN` from every subprocess environment, so no
  request the mock ever sees could carry a token whether the guard is there or
  not. `_Handler.do_GET` (`tests/test_check_action_pins.py:104-129`) also
  discards headers entirely. The mock is already pointed at `127.0.0.1:<port>`,
  which is exactly the arbitrary-`GITHUB_API_URL` case the Must Have calls out
  in bold, so the fixture needed is already standing up. Have the handler
  record `self.headers.get("Authorization")` on the server, add a case that
  sets `GH_TOKEN` (and one that sets `GITHUB_TOKEN`) in the subprocess env
  while `GITHUB_API_URL` points at the mock, and assert every recorded value is
  `None`. For a hardening check whose whole subject is supply-chain safety,
  leaking a CI credential to a redirected API base is the failure mode most
  worth locking down in a test.

## Non-blocking notes

- **N1: the mismatch case does not assert aggregation**
  (`tests/test_check_action_pins.py:211-222`): the Must Have requires that
  every failure is reported, not just the first, and `mismatch` mode makes all
  seven pins fail, but the test only looks for `workflow_pins()[0]`. Assert
  that every pin's `repo`/`sha` appears in stderr so the aggregation behaviour
  is actually covered.

- **N2: the mock's commit table collapses pins that share a repo**
  (`tests/test_check_action_pins.py:72-73`): `_expected_commits()` keys by
  `pin.repo`, so two workflows pinning the same `owner/repo` at different tags
  would leave the mock answering both with one SHA and the "verified" case
  failing for a reason that has nothing to do with the script. Harmless today
  (`step-security/harden-runner` and `actions/checkout` are pinned identically
  in both workflows); keying by `(repo, tag)` removes the trap.

- **N3: two comma-spliced appositive lists read as run-ons**
  (`docs/architecture.md:275-281`): "a network failure in such a check, an
  unreachable host, a rate-limit response, a persistent server error, fails the
  run" and "a future one, an integration test against a live service, say,
  follows the same contract" both lose the subject before the verb arrives. The
  no-em-dash rule is satisfied; recast each as two sentences or a colon so the
  list does not read as a compound subject.

- **N4: folding the `resolve_commit` fix into the Step 2 commit is fine**
  (`37a8a36`, `tools/check-action-pins.sh:88-137`): adjudicated, no action.
  The fix is correct: `classify_status` set `RESOLVE_ERR` inside the command
  substitution that ran `resolve_commit`, so the variable died with the
  subshell and every failure line printed a blank reason. Returning the reason
  on stdout is the right shape given the caller already captures stdout, and
  the success and failure paths stay unambiguous because the success path
  prints nothing else. Folding it into the commit that added the test is the
  correct grouping, since that test is what exposed it, and the commit message
  calls the fix out in its own paragraph rather than burying it.

- **N5: `CHECK_ACTION_PINS_RETRY_SLEEP` is acceptable as-is**
  (`tools/check-action-pins.sh:20-22`): adjudicated, no action. It is not
  undocumented; the script's `Env:` header block describes it and states why it
  exists ("tests set 0 so the retry path does not stall"), which is the right
  place for a tools-internal knob. It does not belong in `docs/`, since it is
  not a user-facing option, and the name is already scoped to the script. The
  alternative, a real sleep in the 5xx test, would trade a documented knob for
  a slow suite.
