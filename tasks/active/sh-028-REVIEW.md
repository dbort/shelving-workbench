# sh-028 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (exit 0; ruff, `ruff format
--check`, `mypy` over 46 files, 238 pytest items including 36 in
`tests/test_task_status.py`, both FreeCAD smokes). The findings below are
about report correctness and test coverage, not a red check.

## Blocking findings

- **F1: `tasks/active/sh-XXX-REVIEW.md` is reported as if it were a task
  file** (`tools/task_status.py:238`, `tools/task_status.py:470-496`):
  `build_report` iterates every `*.md` in `tasks/active/` and derives the
  task id with `_PATH_ID_RE` (`(?:^|/)(sh-\d+)-[^/]+\.md$`), which matches
  `sh-028-REVIEW.md` and yields `sh-028`. The rejection loop
  (`.claude/docs/pipeline.md` § The rejection loop) puts exactly that file
  in `tasks/active/` on every rejected round, so this is a state the
  pipeline itself creates routinely, and this very review round creates it
  for sh-028.

  Reading the code, the consequence is: for each such file the loop calls
  `read_authoritative_task_text(repo, "sh-028", <REVIEW path>)`, the branch
  `sh-028` exists, so the text comes from the branch's real task file and
  parses cleanly with a matching id. The entry is then appended with
  `path=task_path.relative_to(repo_root)` (line 496), i.e.
  `"tasks/active/sh-028-REVIEW.md"`. The JSON `tasks` array therefore
  carries two entries with `"id": "sh-028"`, one of which advertises the
  REVIEW file as the task's path. That contradicts Must Have 5's stated
  contract for `path` ("the task file's path relative to the repo root ...
  so a caller never has to guess or re-derive the slug"), and a duplicate
  `id` breaks any consumer keying the array by id. `render_human_report`
  hides rather than fixes it: `entry_by_id` (line 613) is a
  last-write-wins dict, so one of the two entries is silently dropped from
  the Markdown view.

  Decide the behavior deliberately (skip non-task `*.md` files in
  `tasks/active/`, or list them under some other key) and pin it with a
  committed test: a fixture repo with both `sh-00X-slug.md` and
  `sh-00X-REVIEW.md` in `tasks/active/`, asserting the resulting `tasks`
  array's ids and `path` values.

- **F2: the JSON output path has no automated test at all**
  (`tools/task_status.py:559-585`, `tools/task_status.py:635-659`;
  `tests/test_task_status.py:17-32`): nothing in the test module imports
  or exercises `report_to_json` or `main`. Must Have 2 ("Running it with
  no arguments prints one JSON object to stdout and exits 0") and Must
  Have 3 (the top-level key set) are currently verified only by the
  Execution Plan's by-hand `pixi run task-status` run, which leaves no
  trace and which no future author knows to repeat. `report_to_json` is
  not a trivial passthrough either: `_entry_to_json` dispatches on the
  `NormalTaskReportEntry`/`ErrorTaskReportEntry` union and hand-copies
  twelve keys, and `main`'s exit code and `--human`-vs-JSON branch are
  equally uncovered. The repo already has the convention for this:
  `tests/test_check_lock_paths.py:61-78` tests both `main([...])`'s return
  code and the CLI entrypoint. Add tests that assert the serialized
  report's top-level keys, a normal entry's full key set, an error entry's
  `{"id", "error"}` shape, and `main([]) == 0` producing parseable JSON.

- **F3: the report-level `circular_blocked_by` anomaly is never asserted**
  (`tools/task_status.py:512-514`; contrast
  `tests/test_task_status.py:447-452`): Must Have 10 requires every task
  in a cycle to appear in the top-level `anomalies` array.
  `test_layered_topological_order_cycle_is_reported_not_hung`
  (`tests/test_task_status.py:265-270`) covers the pure function's
  `cyclic_ids` return, and `test_render_human_report_ordering_and_fields`
  covers cycle ordering in the Markdown view, but no test asserts
  `Anomaly(id=..., reason="circular_blocked_by") in report.anomalies` the
  way the `done_in_active` twin does. The fixture repo in
  `test_render_human_report_ordering_and_fields` already contains an
  sh-006/sh-007 cycle, so this is an assertion away.

## Non-blocking notes

- **N1: the "exactly two top-level keys" contradiction was resolved
  correctly** (`tasks/active/sh-028-task-status-tool.md:35-37`): shipping
  four top-level keys (`next_id`, `tasks`, `errors`, `anomalies`) is the
  only self-consistent reading of the Must Have list, since the later Must
  Haves require a top-level `"errors"` array (line 77-78) and a top-level
  `"anomalies"` array (lines 82-84, 91-92), and Frontier Advice restates
  it ("report them as data (`"errors"`, `"anomalies"`)", lines 244-245).
  The "exactly two" phrasing is a drafting artifact predating those lines.
  No code change wanted here; the task file's own wording is what is
  stale, and correcting it is a human/Planner edit at sign-off, not an
  Implementer edit to an approved contract.
- **N2: `main` cannot be pointed at a fixture repo**
  (`tools/task_status.py:635-650`): it calls `_repo_root()` with no
  override, which is part of why F2's coverage is missing. An optional
  repo-root parameter (or a `--repo-root` flag) would let a test drive the
  whole CLI against the same throwaway repos the rest of the suite builds,
  the way `check_lock_paths.main([str(lock)])` already works. Testing
  `main([])` against the real repo and asserting exit 0 plus parseable
  JSON is an acceptable alternative if you would rather not widen the CLI.
