# sh-011 Review — Round 3 (sign-off re-review)

**Verdict:** REJECTED

This is a re-review of the user-directed sign-off edits (`83da393..HEAD`), not a
rejection-loop round. `review_rejections` stays at **1** and this round does not
count toward the cap of 3. The rest of the branch already passed rounds 1 and 2
and was not re-examined.

`pixi run tests`: **green**, exit 0. `check_lock_paths` OK, ruff lint + format
clean, `mypy --strict` clean over 29 source files (including the new
`freecad/shelving/objects/feature_types.py`), shellcheck OK, vendor drift OK,
146 pytest passed, workflow lint OK, both `freecadcmd` smokes printed their
markers (`shelving workbench import OK`, `shelving object layer OK`).

Everything the sign-off brief asked me to confirm about the code checks out:
the `PlankFeature` Protocol surface still matches every `addProperty` /
`setEditorMode` call in `Plank.__init__`; the rename left no dangling import in
`freecad/`, `tools/`, or `tests/`; all three `plank_shape` call sites pass
positionally; `plank_shape(size, origin)` is sound under the units-in-the-name
rule and matches existing practice in `shelving_core/expand.py:54-55,80`, which
already names `Vec3`-typed fields and parameters `size` / `placement`; no
`# COMMENT:` markers remain anywhere; `tools/run-tests.sh` needed no change.

The two findings below are both about record-keeping that the rename and the
probe removal left behind, not about the code.

## Blocking findings

- **F1: friction-log entry deleted without a fix and without a record**
  (`.claude/docs/friction-log.md`, deleted in commit `69e9303`): that commit
  removes the `2026-09-03` entry **"`App::Part` rejects a `Proxy` assignment, so
  the sh-011 probe pseudocode crashes as written"**. Nothing about that deletion
  appears in `69e9303`'s commit message (which describes the catalog rename, the
  `Vec3` parameter names, the README trim, the `add_plank` comment, and the *new*
  mypy-`files` entry), and nothing about it appears in the task file's
  `## Sign-off addendum` (`tasks/active/sh-011-freecad-object-layer.md:35-57`),
  which is otherwise an accurate record of rounds A and B.

  This violates the log's own protocol
  (`.claude/docs/friction-log.md:23-27`): a papercut entry is deleted only in the
  dedicated commit that *fixes* it, "whose message records BOTH the original
  papercut... AND how it was solved", and "sweeping the log is a human-triggered
  act... no agent schedules one on its own". Contrast the deletion in `098b33f`,
  which is compliant: dedicated commit, message states the papercut and the fix.

  The papercut here was not fixed. It records a defect in the *task's* PROBE
  pseudocode (it assumed a bare `App::Part` could hold a `Proxy`), and its
  "Simpler if" is a lesson addressed to the Planner. Dropping the probe in
  `db325f6` does not fix that, and the deletion in fact lands one commit *before*
  the probe removal. The behavioral knowledge survives in
  `docs/freecadcmd-notes.md:49-64`, but the planning lesson does not.

  To clear this, either restore the entry verbatim (it is recoverable with
  `git show 83da393:.claude/docs/friction-log.md`), or, if the user asked for the
  deletion during sign-off, record that directive in the `## Sign-off addendum`
  so the removal is accounted for. Do not delete it in a commit whose subject is
  about something else.

- **F2: the rename leaves `sh-012`'s plan pointing at a module that no longer
  exists** (`tasks/active/sh-012-shelving-unit-container.md:60`, `:104`, `:207`):
  all three still name `freecad.shelving.catalog` / `freecad/shelving/catalog.py`,
  which `69e9303` renamed to `default_catalog.py`. Line 207 asserts as fact that
  after sh-011 lands, "`freecad/shelving/catalog.py` (`DEFAULT_CATALOG`,
  `DEFAULT_MATERIAL_ID`, `DEFAULT_CATALOG_IDS`) all exist" — false the moment this
  branch merges. Line 60 is a `## Must Have` checkbox item ("enum list =
  `freecad.shelving.catalog.DEFAULT_CATALOG_IDS`") and line 104 is an explicit
  import instruction.

  This is not hypothetical or deferrable: sh-012 is `blocked_by: [sh-011]` and is
  already sitting at `current_phase: implementation`, so it dispatches as soon as
  sh-011 merges. An Implementer following the plan literally writes a broken
  import, and an sh-012 Reviewer checking that Must Have against the code finds a
  mismatch either way. A rename that breaks a sibling's plan is the rename's debt
  to settle.

  Fix: update those three literal module paths to `default_catalog` and change
  nothing else in sh-012's file. This is a mechanical path correction, not a
  re-plan.

## Non-blocking notes

- **N1: the notes file's intro promise no longer holds for its last section**
  (`docs/freecadcmd-notes.md:5-6`): "Several of its behaviors differ from a plain
  `python script.py` run; each is handled in the code cited below." The first
  three sections each cite code (`tools/run-tests.sh`, `tools/freecad_smoke.py`,
  `freecad/shelving/init_gui.py`). The `App::Part` section (`:49-71`) cited
  `tools/freecad_object_smoke.py::_probe_apart_execute` before `db325f6`; it now
  cites nothing, so "each is handled in the code cited below" is no longer true of
  it. The count word "Several" reads fine for four sections. Rewording the intro
  clause, or noting in the section that the finding is recorded rather than
  checked, would settle it. Fold into whichever round addresses F1/F2.

- **N2: the `App::*Python` positive control is now an untested documentation
  claim** (`docs/freecadcmd-notes.md:62-64`): the assertion that
  `App::FeaturePython`, `App::GeometryPython`, and
  `App::DocumentObjectGroupPython` receive `execute` on every `recompute()` used
  to be backed by the probe's positive control, which `pixi run tests` ran on
  every invocation. It is now prose only, so a future FreeCAD bump that changes
  it goes unnoticed until sh-012's container misbehaves. The user directed the
  probe's removal, so this is recorded rather than raised against the
  implementation; sh-012 will exercise the surviving half of the claim anyway
  when its container recomputes. No action needed on this branch.

- **N3: the `## Sign-off addendum` omits one Round B item**
  (`tasks/active/sh-011-freecad-object-layer.md:44-57`): it does not mention the
  comment added to `add_plank` explaining why `Plank(obj)` binds nothing
  (`freecad/shelving/objects/plank.py:34-35`), which `69e9303`'s commit message
  does list. Trivial next to F1, but worth adding in the same edit that resolves
  F1's addendum question. Rounds A and B are otherwise accurate, and the
  `review_rejections` note ("stays at 1") is correct.
