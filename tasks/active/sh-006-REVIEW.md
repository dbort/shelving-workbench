# sh-006 Review — Round 3

**Verdict:** REJECTED

Third review pass on this branch (`review_rejections` is now 2). The
bash → Python rework in `e079300` is otherwise sound: `pixi run tests` is
green with `check-action-pins: verified 7/7 pins`, `pixi run tests --
--offline` is green with `check-action-pins: skipped (SHELVING_OFFLINE)`,
`mypy` covers 15 source files (13 before, plus the two new ones, so
`explicit_package_bases = true` hides nothing), `shellcheck tools/*.sh`
passes without `check-action-pins.sh`, and
`git grep -n 'check-action-pins\.sh' -- ':!tasks/'` is empty. One blocking
gap.

## Blocking findings

- **F1: the 5xx retry loop is never exercised by a test**
  (`tools/check_action_pins.py:247-257`, wired at `tools/check_action_pins.py:291`):
  `_retrying_fetch` re-issues a request while the status is 5xx, up to two
  extra attempts, and `main` wraps the resolving fetch in it. No test drives
  that path. `tests/test_check_action_pins.py:101-120` only asserts the
  wording `classify_status` produces for 500/503 ("server error ... after
  retries"), which is a pure function that never retries anything; the four
  `main` tests pass `retry_sleep=0.0` but supply fetches that return 200 or
  are never called. Nothing fails if the retry count is wrong, if the bound
  changes from 2, or if `_retrying_fetch(...)` is dropped from line 291
  entirely — in which case `classify_status`'s "after retries" message would
  become a lie while the suite stayed green. The rework's own premise is that
  the injectable design makes this testable without a server
  (`## Rework` R1: "retry sleep injectable / an arg defaulting to ~1s, so a
  unit test sets 0 or patches `time.sleep`"), and `## Must Have` only excused
  this path when the HTTP mock could not express it. Add a committed unit
  test that drives the retry path through `main` (or through the retry
  wrapper plus `resolve_commit`) with `retry_sleep=0.0`: a counting fetch
  returning HTTP 500, asserting the exact number of attempts per pin (3),
  a non-zero exit, and the `server error (HTTP 500) ... after retries` reason
  on stderr. Cover that the loop stops retrying once a retry succeeds, so the
  bound is pinned from both sides.

## Non-blocking notes

- **N1: the userinfo look-alike host is untested**
  (`tests/test_check_action_pins.py:269-279`): the parametrised
  `auth_headers` cases cover `https://api.github.com.evil.com`, but not
  `https://api.github.com@evil/`, where the real host sits after the `@`.
  `urllib.parse.urlsplit(...).hostname` returns `evil` there, so
  `tools/check_action_pins.py:151` withholds the header and the behaviour is
  right; it is the same branch the existing cases already reach, so this is
  one more parametrise entry rather than new coverage. Worth adding while
  F1 is in flight, since this is the token-leak guard.

- **N2: two diagnostics lost detail against the shell version**
  (`tools/check_action_pins.py:115`, `tools/check_action_pins.py:301`): the
  connection-failure reason reads "cannot reach the API for ..." where the
  shell version interpolated the actual base URL, which mattered exactly when
  `GITHUB_API_URL` was overridden to something unreachable; and failure lines
  now name `path.name` (`ci.yml`) where the shell version carried the
  workflow path (`.github/workflows/ci.yml`). Neither changes an outcome.

- **N3: the script header still walks through the checks**
  (`tools/lint-workflows.sh:5-18`): `## Rework` R3 asks for the same
  judgement applied "to any other doc prose that walks through a script's
  steps", and this numbered five-item list restates the five `run_check`
  calls sitting 50 lines below it. The diff extended the list instead of
  trimming it. The non-obvious part (the offline/online split and the
  `SHELVING_OFFLINE` escape) is worth keeping; the enumeration is not.

- **N4: a non-JSON 200 escapes as a traceback**
  (`tools/check_action_pins.py:224-228`): `json.load` inside the `urlopen`
  block raises `ValueError`, which is neither an `HTTPError` (handled) nor an
  `OSError` (`_fetch_catching` at line 172 converts those to status 0), so a
  proxy or captive portal answering 200 with HTML crashes with a traceback
  rather than a classified fatal reason. The outcome is still fatal and
  non-zero, so the two-outcome contract holds; the message is just worse than
  the rest of the module's.
