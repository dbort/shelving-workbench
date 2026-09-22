---
id: sh-028
title: "A deterministic task-status reporting tool"
current_agent: reviewer
current_phase: review
review_rejections: 0
---

# sh-028: A deterministic task-status reporting tool

## Summary
Every skill that touches `tasks/active/*.md` (`dispatch-tasks`, `approve-task`,
`new-task`) currently re-derives the same facts by hand each time: which
tasks are unblocked, which are mid-pipeline and whether their branch
exists yet, and the next free `sh-XXX` id, via ad hoc `git`/`grep`/`ls`
commands in the skill's own prose. This adds a single, tested Python
script that computes all three deterministically and prints them as JSON,
so a skill (or a human) can call one command instead of re-deriving
pipeline state by hand. It reports only; nothing in this task changes how
any skill actually advances a task's phase, and no skill is migrated to
call it yet.

## Status
- [x] Planning
- [x] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `tools/task_status.py` is a real script, runnable as
      `python3 tools/task_status.py` and as `pixi run task-status`
      (a new `pixi.toml` `[tasks]` entry). Running it with no arguments
      prints one JSON object to stdout and exits 0.
- [x] The JSON object has exactly two top-level keys: `next_id` (a string,
      e.g. `"sh-029"`) and `tasks` (an array, one entry per file in
      `tasks/active/`, in the same order `ls tasks/active/` would give).
- [x] `next_id` is computed from the highest existing `sh-NNN` found across
      ALL of: the working directory's own `tasks/active/`,
      `tasks/completed/`, `tasks/abandoned/` listing (including anything
      uncommitted); AND, for every local branch (`git for-each-ref
      refs/heads/`), that same three-directory listing as it exists at
      that branch's own tip (`git ls-tree`, not a checkout). A task
      created on one branch, or accumulated on `main` while another branch
      was checked out, must not collide with an id this tool hands out
      from a different, stale-relative-to-it branch. Add one to the
      highest id found across that whole union, zero-padded to match the
      existing numeral width — the padding-width rule is `new-task`'s own
      Task ID Allocation algorithm (`.claude/skills/new-task/SKILL.md`),
      now applied to a wider id set than a single branch's tree.
- [x] Each `tasks` entry is an object with: `id`, `title`, `path` (the
      task file's path relative to the repo root, e.g.
      `"tasks/active/sh-025-scan-divider-void-height.md"`, so a caller
      never has to guess or re-derive the slug), `current_phase`,
      `current_agent`, `review_rejections`, `blocked_by` (array, empty when
      absent from the frontmatter), `unmet_blockers` (array: the
      `blocked_by` ids NOT present in `tasks/completed/`), `blocked`
      (`unmet_blockers` non-empty), `in_progress` (`current_phase` is not
      `"planning"`), `branch_exists` (a local branch named exactly the
      task's id exists), and `source` (`"working_tree"`, or
      `"branch:sh-XXX"` naming the branch the frontmatter was actually
      read from).
- [x] Per-task frontmatter is read from the authoritative location, not
      assumed from the working tree: if a branch named exactly the task's
      `id` exists, read `git show sh-XXX:tasks/active/sh-XXX-*.md` (falling
      back to `git show sh-XXX:tasks/completed/sh-XXX-*.md` if the first
      path doesn't exist on that branch — a task whose `approve-task` run
      finished finalizing but hasn't merged yet); only trust the plain
      working-tree file when no such branch exists. This is
      `dispatch-tasks`' own Step 1 logic (`.claude/docs/pipeline.md` §
      Git branching, and `dispatch-tasks/SKILL.md` Step 1), now centralized
      here instead of re-derived per skill invocation.
- [x] A task file that fails to parse (missing a required frontmatter key,
      malformed YAML, `id` in the frontmatter not matching the `sh-XXX` in
      its filename) does not crash the whole report: that task's entry
      carries an `"error"` string field instead of the normal fields, and
      every other task still reports normally. A top-level `"errors"`
      array lists every task id that hit this path, empty when none did.
- [x] A task file whose `current_phase` is `"done"` while still sitting in
      `tasks/active/` (the anomaly `.claude/docs/pipeline.md` § Phases
      already names) is still reported normally (all its real fields
      populated) but also added to a top-level `"anomalies"` array of
      `{"id": ..., "reason": "done_in_active"}` objects, empty when there
      are none.
- [x] `tasks/completed/` and `tasks/abandoned/` entries themselves are never
      listed in the `tasks` array; they're consulted only to resolve
      `unmet_blockers` and `next_id`.
- [x] A `blocked_by` cycle among two or more `tasks/active/` entries (a
      genuine authoring error, but the tool must not hang or crash on one)
      is detected, not silently mis-ordered: every task caught in the
      cycle is added to the top-level `"anomalies"` array as
      `{"id": ..., "reason": "circular_blocked_by"}`.
- [x] `--human` (see Frontier Advice for the short-flag naming — do not
      collide with argparse's own `-h`/`--help`) prints a Markdown summary
      to stdout instead of JSON, exit 0, in this exact shape — one
      top-level bullet per task, its own fields as an indented, nested
      bullet list beneath it, not one dense line:
      ```
      Next id: sh-029

      - sh-019: The material catalog as a document object
        - path: tasks/active/sh-019-material-catalog.md
        - phase: planning
        - blocked by: (none)
      - sh-020: The elevation editor: structure
        - path: tasks/active/sh-020-elevation-editor-structure.md
        - branch: sh-020
        - phase: implementation
        - blocked by: sh-019
      ```
      The `branch` line is present only when `branch_exists` is true
      (omitted entirely otherwise, not printed as "none"). The `blocked
      by` line lists `unmet_blockers` (blockers not yet in
      `tasks/completed/`), comma-separated, or the literal `(none)` when
      empty — an already-completed blocker never appears here, unlike the
      JSON's `blocked_by`, which keeps the raw frontmatter list. No
      `current_agent`, `review_rejections`, `source`, or the JSON's other
      fields appear in this view at all.

      Entries are ordered by a layered topological sort over the
      `blocked_by` DAG restricted to edges between two tasks both
      currently in `tasks/active/` (an already-completed, abandoned, or
      nonexistent blocker id contributes no edge and does not hold a task
      back): every task with zero remaining unresolved-within-`tasks/
      active/` blockers forms the first layer, printed first; removing
      that layer's ids from every remaining task's blocker set produces
      the next layer, and so on, so that completing tasks in the printed
      order would unblock each following one exactly when it is reached.
      Ties within a layer sort by `id`. A task caught in a
      `circular_blocked_by` cycle is appended after every orderable layer,
      sorted by `id` among the other cyclic tasks, since it cannot be
      placed correctly.
- [x] The frontmatter-parsing, `blocked_by`-resolution, `next_id`-from-a-
      given-id-set, and layered-topological-sort logic are plain functions
      taking already-loaded data (parsed frontmatter dicts, a set of
      completed ids, a list of existing numeric ids, a mapping of active
      id to its `blocked_by` list) as arguments, importable and
      unit-tested directly with synthetic input, no git subprocess or real
      filesystem involved. Only the thin layer that walks `tasks/*/` (in
      the working tree and across every local branch), invokes `git`, and
      assembles the final report needs a real (temporary, throwaway) git
      repo fixture in its own tests.
- [x] `tests/test_task_status.py` covers: `next_id` computation (including
      the zero-padding-width case); `blocked`/`unmet_blockers` for an
      unblocked task, a task blocked on one id, and one blocked on
      multiple; the `working_tree` vs `branch:sh-XXX` `source` distinction
      (a temp repo with a task file changed on its own branch but not on
      the working tree's checked-out branch); a malformed task file
      producing an `"error"` entry without crashing the rest of the
      report; the `done_in_active` anomaly; the empty-`tasks/active/` case
      (`next_id` still computed, `tasks: []`); `next_id` correctly
      accounting for a task that exists only on a non-checked-out local
      branch, not in the working tree's own listing; the layered
      topological sort for a simple chain, a diamond (two tasks sharing
      one blocker, both unblocking a third), and a genuine cycle (reported
      as `circular_blocked_by` and appended last, not hung or dropped);
      and the `--human` output's nested-bullet shape, field set (including
      that an already-completed blocker is excluded from its `blocked by`
      line, unlike the JSON's raw `blocked_by`), and ordering, end to end
      against a small synthetic repo.
- [x] `mypy --strict` clean. No bare `Any`; the frontmatter dict `yaml.safe_load`
      returns is narrowed into a typed structure (a `TypedDict` or a small
      dataclass) before anything else touches it, not passed around as
      `dict[str, Any]`.
- [x] `pyyaml` is added to `pixi.toml`'s `[dependencies]` (conda-forge). If
      a conda-forge `types-pyyaml` (or equivalent stub) package exists, add
      it too so `mypy --strict` type-checks the `yaml.safe_load` call
      without a bare `Any`; if none exists, a narrow, commented
      `# type: ignore[...]` at the one `safe_load` call site is the
      documented exception (`CLAUDE.md` § Standing task-planning
      obligations: `Any` allowed only at a boundary that genuinely erases
      the type, with a comment saying why).
- [x] No skill (`new-task`, `dispatch-tasks`, `approve-task`) is edited to
      call this tool. That migration is explicitly out of scope for this
      task.

## Frontier Advice

`-h` IS ALREADY TAKEN. `argparse.ArgumentParser` registers `-h`/`--help`
automatically; adding `-h` as a second, different flag raises at parser
construction. Use `-H` (capital) as the short form, or no short form at
all — either is fine, just do not pass `add_help=False` to silently steal
`-h` for this instead, since losing `--help` on a small CLI tool is a
worse trade than an uppercase short flag.

MULTI-BRANCH `next_id` SCANNING, PRECISELY. For each local branch name
from `git for-each-ref --format=%(refname:short) refs/heads/`, run one
`git ls-tree -r --name-only <branch> -- tasks/active/ tasks/completed/
tasks/abandoned/` to list that branch's task files at its own tip, no
checkout involved. Separately, glob the actual working directory's three
`tasks/*/` folders directly (not via `git ls-files`, so an uncommitted new
task file is still counted). Union every `sh-NNN` id extracted from every
path in both sources; that union, not any single branch's or the working
tree's listing alone, is what `next_id`'s "highest existing id" is
computed over.

THE TOPOLOGICAL SORT IS KAHN'S ALGORITHM, LAYERED, NOT A PLAIN DFS ORDER.
A DFS-based topological sort also produces *a* valid ordering where no
task precedes its blockers, but does not naturally group "everything
unblocked right now" into one alphabetically-sorted layer the way the
Must Have describes and a human reader would expect from "position in the
dependency tree." Compute in-degree per active task as the count of its
`blocked_by` ids that are themselves keys in the active-task set (an id
referencing a completed, abandoned, or unknown task contributes nothing);
repeatedly take the whole current zero-in-degree set, sort it by `id`,
append it as one layer, then decrement in-degree for every remaining
task that listed any of those ids. Tasks never reaching in-degree zero
are the `circular_blocked_by` set from the Must Have above.

THIS IS A REPORTING TOOL, NOT A PHASE-TRANSITION MECHANISM. Do not add any
capability that writes to a task file, creates a branch, or otherwise
changes repository state. `.claude/docs/pipeline.md` § Phase transitions
states a hard rule that phase transitions happen only through the owning
skill (`new-task`/`dispatch-tasks`/`approve-task`); a general-purpose
"advance the task stage" primitive is a deliberate, separate follow-up
task once this reporting tool exists and something has actually started
consuming it, not something to fold in here even if it looks like a small
addition once the parsing/git layer already exists.

WHY A HAND-ROLLED FRONTMATTER SHAPE ANYWAY, DESPITE USING A REAL YAML
LIBRARY. `pyyaml.safe_load` handles the actual parsing, but do not treat
its return value as arbitrary YAML: every real task file's frontmatter is
exactly five or six flat keys (`id`, `title`, `current_agent`,
`current_phase`, `review_rejections`, optional `blocked_by`), confirmed by
reading every file in `tasks/completed/` and `tasks/active/` during
planning. Validate that the loaded object is a flat mapping with exactly
the expected keys (plus the optional one) and raise the task's own parse
error (caught and turned into the `"error"` field per the Must Have above)
for anything else, rather than silently accepting an unexpected shape.

READ `.claude/skills/dispatch-tasks/SKILL.md` Step 1 AND
`.claude/docs/pipeline.md` § Git branching BEFORE WRITING THE
AUTHORITATIVE-READ LOGIC. Both already state the exact branch-existence
and `git show` fallback sequence this task's Must Haves describe; this
task is centralizing that logic, not inventing new semantics for it. Get
this exactly consistent with what `dispatch-tasks` already does by hand,
since the eventual point of this tool (a later task) is for
`dispatch-tasks` to call it instead of re-deriving the same thing.

ANOMALIES AND ERRORS ARE DATA, NOT FAILURES. The whole point of a
reporting tool is that it does not crash or refuse just because one task
file is malformed or a `done` task got stranded in `tasks/active/` —
those are exactly the conditions a human or a skill would want *this tool*
to surface, so it must keep working around them and report them as data
(`"errors"`, `"anomalies"`) rather than raising. The process exit code is
0 whenever the report itself was successfully produced, regardless of
what it contains; a nonzero exit is reserved for the tool genuinely being
unable to run (e.g. `tasks/active/` missing, `git` not on `PATH`).

NOT A `pixi run tests` GATE. Unlike `tools/check_lock_paths.py` (a pass/fail
check `tools/run-tests.sh` runs on every invocation), this tool has no
pass/fail condition of its own to gate on; do not add it as a new step in
`tools/run-tests.sh`. Its own tests (`tests/test_task_status.py`) are
collected by the existing `pytest ... tests` step the same way
`test_check_lock_paths.py` already is.

`title` MAY LEGITIMATELY CONTAIN A COLON, so parse it as an actual
YAML-quoted string via the library (`pyyaml`), never with a hand-rolled
`key: value` split on the first `:` — several real task titles already
contain a colon-free but comma-, apostrophe-, or quote-bearing phrase, and
a naive splitter would mishandle a quoted value containing `: `.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python throughout, `mypy --strict`
clean, no bare `Any`/bare containers. This task adds one new dependency
(`pyyaml`) to `pixi.toml`; it does not touch `pyproject.toml` (no runtime
package metadata lives there since `sh-027`, per that file's current
`[tool.ruff]`/`[tool.mypy]`-only shape). Shell stays simple: no shell
script in this task at all; the `pixi run task-status` entry is a one-line
`[tasks]` addition, not a new `.sh` file.

## Execution Plan

- [x] **Step 1** (`tools/task_status.py`, `tests/test_task_status.py`):
      Create the module's pure, git-free core: a `TaskFrontmatter`
      typed structure (dataclass or `TypedDict`); `parse_frontmatter(text:
      str) -> TaskFrontmatter` using `yaml.safe_load` on the `---`-delimited
      block, validating the flat-mapping shape per Frontier Advice and
      raising a dedicated exception (e.g. `TaskParseError`) on anything
      else; `compute_next_id(existing_ids: Sequence[str]) -> str` (the
      zero-padding-aware allocator, taking the already-unioned id set as
      input — the union itself is Step 2's job); `resolve_blocking(
      blocked_by: Sequence[str], completed_ids: AbstractSet[str]) ->
      tuple[list[str], bool]` returning `(unmet_blockers, blocked)`; and
      `layered_topological_order(blocked_by_by_id: Mapping[str,
      Sequence[str]]) -> tuple[list[list[str]], list[str]]` (Kahn's
      algorithm per Frontier Advice, returning the ordered layers and,
      separately, the ids caught in a cycle). Unit tests for all four
      against synthetic strings/lists/mappings only, no filesystem or git;
      the topological-sort tests cover a chain, a diamond, and a cycle.
- [x] **Step 2** (`tools/task_status.py`, `tests/test_task_status.py`):
      Add the git/filesystem layer: a function that lists `tasks/active/`,
      `tasks/completed/`, `tasks/abandoned/` filenames in the working
      directory; a function implementing the multi-branch `next_id` input
      union per Frontier Advice (`git for-each-ref` plus one `git ls-tree`
      per local branch, unioned with the working-directory listing); a
      function implementing the authoritative-read sequence (branch-exists
      check, `git show` with the `tasks/active/` → `tasks/completed/`
      fallback, working-tree fallback) per the Must Haves above, returning
      the raw text plus which `source` it came from; and the assembly
      function building the full report dict from all of the above,
      converting a caught `TaskParseError` into an `"error"` entry and
      detecting the `done_in_active` and `circular_blocked_by` anomalies.
      Test this layer against a temporary git repository your test fixture
      creates and tears down (branches, task files, and commits built with
      real `git` subprocess calls), covering every case the Must Haves
      list, including a task that exists only on a non-checked-out branch.
- [x] **Step 3** (`tools/task_status.py`, `pixi.toml`): Add the CLI entry
      point (`argparse`, since Step 4 adds a real flag next) that calls
      the Step 2 assembly function against the real repo root and prints
      the JSON to stdout by default, exiting 0. Add `pyyaml` (and its type
      stubs if available) to `pixi.toml`'s `[dependencies]` and a
      `task-status = "python tools/task_status.py"` entry to `[tasks]`.
      Run `pixi run task-status` against this actual repo by hand and
      confirm the printed JSON's `next_id` and `tasks` entries look
      correct for the real current state of `tasks/active/`.
- [x] **Step 4** (`tools/task_status.py`, `tests/test_task_status.py`):
      Add the `--human`/`-H` argparse flag (see Frontier Advice on `-h`
      already being taken) and the Markdown renderer it calls: given the
      assembled report and `layered_topological_order`'s output, print the
      next id, then the nested-bullet block the Must Have specifies for
      each task in layer order (alphabetical within a layer, cyclic tasks
      appended last and sorted by `id` among themselves), with `blocked
      by` sourced from `unmet_blockers`, not raw `blocked_by`. Run
      `pixi run task-status -- --human` (or `-H`) against this actual repo
      by hand and confirm the ordering and fields look right.
