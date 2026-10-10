---
next_id: friction-025
---

# Friction log

Moments where developing or testing this repo forced a workaround: a
missing tool, data in the wrong shape, a doc that had to be
reverse-engineered. Log it in the same session, even when the workaround
succeeded. Defects in the shipped workbench go in `bug-log.md` instead.

An entry qualifies only if its fix is something this repo could build or
write. An upstream tool's permanent behavior belongs in a comment at the
call site, `freecad-notes.md`, or a Claude memory.

Format, oldest first:

- `friction-NNN` - **<what was needed>**: what happened; the workaround
  used. Simpler if: <the missing tool/data/doc>.

The id is `next_id` from the front matter; increment it in the same
commit. It only moves forward, even when entries are deleted. An entry
written during task work commits on the task's branch. The commit that
fixes a papercut records the papercut and its fix and deletes the entry.

## Entries

- `friction-019` - **diff-scoped `doc-hygiene` never fixes a pre-existing
  violation that the diff extends**: in sh-019, a docstring listing every
  command id duplicated the `command_ids` list below it, and the diff added
  three ids to both. Two `--diff=main` sweeps left it, because the
  violation predated the diff and the skill scopes edits to "changed lines
  plus any nearby comment they made stale". Fixed by hand on the branch.
  Simpler if: the diff-scoped prompts treated a changed line inside an
  already-violating block as in scope.
- `friction-022` - **a way to run doc-hygiene's embedded workflow script
  outside a real sweep**: changing the JS in
  `.claude/skills/doc-hygiene/SKILL.md` had no check; the environment has no
  JS runtime. The workaround extracted the fenced block with ad hoc Python,
  stubbed `agent`/`pipeline`, and ran it under `pixi exec -s nodejs node`.
  Simpler if: `pixi run tests` extracted the block, stubbed the workflow
  API, and dry-ran it in full-tree and diff-scoped modes.
- `friction-024` - **a manual QA structure that survives edits**: cases in
  `docs/manual-qa.md` are numbered in one sequence, and cases that chain
  share state through **Start** lines, so adding, removing or reordering
  one renumbers others, and a reader cannot always tell what state a case
  expects. Simpler if: cases had stable ids per feature section (EDITOR-1.3)
  and each scenario held its own compound steps.
