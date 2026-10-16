---
next_id: friction-028
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
written during task work commits on the task's branch. A commit that
fixes the entry, or removes the code it concerns, deletes it and records
the papercut and its fix in its message.

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
- `friction-025` - **a way to try a call against FreeCAD's 3D view
  without writing a test**: sh-040 needed a dozen answers from a live view
  (what the selection gate sees over a back panel, how long a camera turn
  animates, whether an aborted transaction leaves an f(x) step). Each probe
  was a one-off script repeating the settings, GUI start and Xvfb launch
  that `tests/freecad_view/conftest.py` already does. Simpler if: a
  `tools/` entry ran a snippet in a 3D view with a fresh document and a
  `ViewDriver`, under the same settings as the view tier.
- `friction-026` - **a 3D view of one known size in every view test**: in
  sh-040 the view was 404 by 300 pixels in one test alone and 1134 by 703
  later in the same run, so pixel-aimed tests passed alone and failed in
  the suite. Each such test sets its camera height from the view's size.
  Simpler if: the `driver` fixture gave each test's view a fixed size.
- `friction-027` - **a comment typed after a case's last step reaches no
  report**: in sh-041's manual QA, the user wrote a padlock finding on the
  "Every step is recorded." page and pressed Finish case; the report has
  no trace of it. `QAWizard._show_step` in `qa/dock.py` disables the
  verdict buttons once every step is recorded but leaves `comment_edit`
  open, and only `record` reads it. The user relayed the comment in chat.
  Simpler if: the finished page either hides the comment box or saves its
  text as a case-level comment in the report.
