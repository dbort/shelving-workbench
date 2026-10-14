---
next_id: bug-016
---

# Bug log

Functional defects in the workbench on `main`: wrong output, a refusal that
should succeed, a crash, behavior that contradicts the design docs or a
task's Must Haves. Log one in the same session when it will outlive that
session. A defect fixed at once gets no entry; its fixing commit describes
it. Friction in building the workbench goes in `friction-log.md`.

Format, oldest first:

- `bug-NNN` - **<what's wrong>**: what a user sees, how it was found, and
  the root cause once known. Fix: `ad hoc` or `sh-XXX task`, with the
  reason for that call.

Ad hoc suits a small, localized fix whose correct behavior is not in
question. A task suits a fix to shared logic or one that needs a design
decision.

The id is `next_id` from the front matter; increment it in the same
commit. It only moves forward, even when entries are deleted. An entry
written during task work commits on the task's branch. A commit that
fixes the entry, or removes the code it concerns, deletes it. Sweeping the
log happens only when the user asks.

## Entries

- `bug-001` - **one untagged box with no single thinnest axis refuses the
  whole scan**: a cube in the container makes Scan and every edit refuse
  with `no single thin axis`, even though an untagged object would only be
  left alone. `_classify_thin_axis` in `core/scan.py` raises from the
  shared per-box loop, while a not-axis-aligned object is merely skipped
  in `container.py`. Found in sh-018's manual QA. Fix: `sh-XXX task`.
  Whether to defer classification until a box's match status is known or
  to redirect every failure to `skipped` is a design question in shared
  scanning logic.
- `bug-004` - **the editor's elevation is drawn far larger than the task
  pane**: the view shows the scene at one pixel per millimeter, so a unit
  needs many screens of scrolling, and nothing fits it to the view or
  zooms. Found in sh-020's manual QA. Fix: `sh-XXX task`. Fit-to-view is
  the minimum, but the user wants the editing interface rethought (zoom
  controls, a full-screen Sketcher-style mode).
- `bug-005` - **after deleting a divider beside a stack of shelves, a
  full-height divider cannot be added back**: the whole-width region is a
  `Division`, and `Session.can_split` and `core.edit.split_region` act only
  on a selected `Bay`, which is all the scene lets you select. Found in
  sh-020's manual QA. Fix: `sh-XXX task`. It needs an edit that splits a
  `Division` across its cross axis and a way to select a region with no
  area of its own, both design questions.
- `bug-007` - **a board moved or thinned by hand snaps back on the next
  edit when a stored `Fill` rule bounds it**: add a shelf and click OK,
  move it down 60 mm by hand, then run `unit_ops.rescan_unit`; it returns
  to the middle. The scan reads the unequal bays correctly, but
  `record.with_stored_rules` overwrites them with the stored `Fill` rules,
  keyed by boards that still exist. This contradicts the design's promise
  that a hand edit is taken up. Found in sh-020's manual QA; sh-030's QA saw
  a thinned shelf re-center 3 mm. Fix: sh-038, which takes sizes from geometry and only the
  lock and basis from the record.
- `bug-009` - **elevation dimensions overlap each other and their
  labels**: `_add_region_dimensions` in `editor/scene.py` places each
  dimension at a fixed fraction of its region's cross extent with no
  awareness of the others. Found in sh-021's manual QA. Fix: `sh-XXX task`;
  where dimensions go (lanes, selected region only, outside the unit) is
  the user's design decision.
- `bug-010` - **a dimension set from an expression keeps only the resolved
  number**: binding `VarSet.Len` sizes the region once, and a later change
  to the `VarSet` moves nothing. The rule record in `core/record.py` holds
  numbers, not a property `ExpressionEngine` can drive. Found in sh-021's
  manual QA. Fix: `sh-XXX task`; storing expressions per region changes
  the record, reflow and the editor.
- `bug-011` - **Edit Unit sometimes takes many seconds to show its
  panel**: 29 s once on FreeCAD 1.1.1, intermittently. `debug_log` shows
  this workbench's code done within 25 ms and the form's first `Show` event
  29 s later, so some ancestor held the form hidden. On the user's 1.1.1 the
  Tasks panel docks in overlay mode, and `Gui::OverlayTabWidget
  'OverlayRight'` is a hidden ancestor after `showDialog`; an overlay panel
  can auto-hide until hovered, so it is the leading suspect.
  `AncestorWatch` in `editor/panel.py` logs the hidden ancestors. Fix:
  `ad hoc`, once a slow run's log confirms the ancestor: raise the overlay
  through FreeCAD's API, or document the setting.
- `bug-014` - **Edit Unit is disabled for boxes selected inside a
  hand-built group that has never been saved as a unit**: selecting one or
  more boxes in the QA case's TestUnit leaves Edit Unit disabled, while
  selecting the group itself works. `container.unit_for_selection` maps
  each selected object to the nearest group carrying a `ShelvingUnitId`,
  and only Create Unit or an Edit Unit OK (`container.write_container`)
  writes one, so a never-saved group is reachable only by selecting it.
  Found in sh-022's manual QA; `main` behaves the same. Fix: `sh-XXX task`.
  The fallback when no selected object has a saved unit above it is a
  design question: the group directly holding every selection is the
  obvious answer, but a box nested in a subgroup or a PartDesign Body
  makes that group the subgroup rather than the unit.
- `bug-015` - **Undo during Edit Unit undoes the whole edit and what came
  before it**: with the panel open, Cmd-Z or the Edit menu's Undo reverts
  every edit made in the panel at once, and a second Undo reverts the step
  before the session, such as Create Unit, while the panel stays open over
  a stale session; OK and Cancel then act on a document the session no
  longer matches. `Std_Undo` is enabled during any task dialog, and with
  `Session.open`'s one transaction still open, FreeCAD commits it and
  undoes it whole. Found in the viewport-editing spike on the user's Mac.
  Fix: sh-039, one transaction per edit.
