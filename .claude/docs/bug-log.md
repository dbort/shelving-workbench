---
next_id: bug-013
---

# Bug log

Functional defects in the workbench on `main`: wrong output, a refusal that
should succeed, a crash, behavior that contradicts the design docs or a
task's Must Haves. Log one in the same session when it will outlive that
session. A defect fixed at once gets no entry, whether on a task branch or
in an ad hoc fix: its fixing commit describes it. Friction in building the
workbench goes in `friction-log.md`.

Format, oldest first:

- `bug-NNN` - **<what's wrong>**: what a user sees, how it was found, and
  the root cause once known. Fix: `ad hoc` or `sh-XXX task`, with the
  reason for that call.

Make the ad-hoc-vs-task call when logging. Ad hoc suits a small, localized
fix whose correct behavior is not in question. A task suits a fix to
shared logic or one that needs a design decision.

The id is `next_id` from the front matter; increment it in the same
commit. It only moves forward, even when entries are deleted. An entry
written during task work commits on the task's branch. The commit that
fixes a bug records the bug and its fix and deletes the entry. Sweeping
the log happens only when the user asks.

## Entries

- `bug-001` - **an untagged object that fails thin-axis classification
  hard-refuses the whole scan, not just that object**: `Shelving_Scan` and
  `Shelving_ResizeUnit` refuse outright when any box in the container has
  no single thinnest axis (e.g. a cube, three tied extents), even when
  that object carries none of this workbench's own properties and was
  always going to end up in `WriteResult.left_alone`, never touching the
  solved layout. `scan()`'s top-level loop
  (`freecad/Shelving/core/scan.py`, the per-box loop calling
  `_classify_thin_axis`) has no fallback: every box must classify or the
  whole call raises `ScanError`. This is inconsistent with how a
  not-axis-aligned object is already handled: that case is gracefully
  added to `Skipped` at the `container.py` classification layer, never a
  hard refusal. Found during `sh-018`'s manual QA sign-off (M7 case 4: a
  cube-shaped `Part::Box` added as a "this workbench ignores it" example
  instead blocked the whole Resize Unit call with `REFUSED: HandAdded: no
  single thin axis`). Worked around for that one doc case by changing the
  example box's dimensions so it isn't a cube
  (`docs/manual-qa.md`, `sh-018` commit `3bd0291`); the underlying gap in
  `scan.py` is untouched. Fix: `sh-XXX task`. `_classify_thin_axis` is
  called from `scan()`'s shared per-box loop, used by every caller, and
  the right restructuring (defer classification until a box's
  match-status against the current layout is known? catch the failure and
  redirect to `skipped` unconditionally? something else?) is a real design
  question, not a mechanical patch, worth a `new-task` interview rather
  than an ad hoc commit into shared scanning logic.

- `bug-004` - **the Edit Unit panel's elevation is drawn far larger than
  the task pane, so a whole unit cannot be seen or worked on at once**:
  the `QGraphicsView` in `freecad/Shelving/editor/panel.py` shows the scene
  at 1 scene unit per pixel, and scene units are millimeters
  (`editor/scene.py`), so a typical unit is several times taller and wider
  than the docked Tasks pane. The user had to scroll down about 12 screens
  and right about 2 to see all of it. Found during `sh-020`'s manual QA
  sign-off. The panel never fits the view to the scene or offers any
  zoom. Fix: `sh-XXX task`. Fit-to-view on open is the obvious minimum,
  but the user wants the editing interface itself rethought. The options
  include zoom in/out controls and a full-screen, Sketcher-style editing
  mode, and choosing between them is a product decision for a `new-task`
  interview.

- `bug-005` - **once a divider is deleted from beside a stack of shelves,
  a full-height divider cannot be added back without first deleting the
  shelves**: starting from the default unit, add a divider, then add a
  shelf on one side, then delete the divider. The shelves now span the
  whole unit, as expected, but no button can now add a divider running the
  full height of the unit. The whole-width region is a `Division` holding
  the shelves, not a `Bay`. `Session.can_split` and `core.edit.split_region`
  act only on a selected `Bay`, and the elevation offers no way to select
  a `Division` region. The only compartments that can be split are the bays
  between the shelves, each of which gets a divider only its own height.
  Found during `sh-020`'s manual QA sign-off. Fix: `sh-XXX task`. It needs
  a new edit, splitting a `Division` region across the cross axis by
  wrapping it (or re-parenting its shelves into two halves). It also needs
  a way to select a non-leaf region in the scene. Which shelves each half
  keeps, and how a user picks a region that has no area of its own to
  click, are design questions and not a mechanical patch.

- `bug-007` - **a board moved by hand snaps back on the next rescan when a
  stored `Fill` rule bounds it**: steps to reproduce:
  1. Create Unit.
  2. In the editor, add one shelf, then click OK.
  3. Move the shelf down 60 mm by hand.
  4. Run `unit_ops.rescan_unit`.

  The shelf returns to z 441.0 from 381.0. The same happens inside the
  editor session, and with Resize Unit. The scan reads the
  moved geometry correctly: the two bays are unequal, so it would assign
  `Fixed`. But `record.with_stored_rules` then overwrites both bays with
  the stored `Fill` rules keyed by their bounding boards, which still
  exist, and the solve puts the shelf back in the middle. This contradicts
  `docs/roadmap.md` M7's "a board moved by hand between operations is
  taken up rather than overwritten". The mechanism predates `sh-020` (it
  comes from `sh-018`'s rule record), but the editor is what makes shelves
  with stored `Fill` rules common. Found during `sh-020`'s manual QA
  sign-off, as a second contributor to the same user report as bug-006.
  A hand thickness change triggers it too: in `sh-030`'s manual QA, a
  shelf thinned from 18 mm to 12 mm by its bottom face re-centered 3 mm on
  the next edit, and the move hid the Woodworking grain-arrow text on it.
  Fix: `sh-XXX task`. A stored rule has to yield when the scanned geometry
  disagrees with what that rule would solve to, but it still has to win
  where geometry is ambiguous (the reason `Basis.WITH_NEXT` is stored).
  Choosing that tolerance and precedence is a design question for
  `new-task`.
- `bug-009` - **elevation dimensions overlap each other and their labels**:
  in the Edit Unit panel, dimensions for different regions draw on top of
  one another, labels included, so some values are unreadable. Found in
  sh-021's manual QA on FreeCAD 1.1.1. Root cause: `_add_region_dimensions`
  in `freecad/Shelving/editor/scene.py` places each dimension line at a
  fixed fraction of its region's cross extent (the center for a bay or
  void, a quarter for a nested division) with no awareness of the other
  dimensions, so nested and neighboring regions collide. Fix: `sh-XXX
  task`, because choosing where dimensions go (offset lanes, drawing only
  the selected region's, moving labels outside the unit) is a design
  decision the user wants to make separately.
- `bug-010` - **a dimension set from an expression keeps only the resolved
  number**: typing `VarSet.Len` or binding it with f(x) sizes the region
  once, but the rule stores the millimeter value, so a later change to the
  `VarSet` moves nothing. FreeCAD users expect a bound length to follow its
  expression. Found in sh-021's manual QA. Root cause: a region's size lives
  in the container's rule record (`freecad/Shelving/core/record.py`), which
  holds numbers, not a document property that `ExpressionEngine` can drive;
  the dimension field binds to a temporary probe object only so it can
  resolve names. Fix: `sh-XXX task`, since storing and re-evaluating
  expressions per region changes the rule record, reflow, and the editor,
  and needs design decisions.
- `bug-011` - **Edit Unit sometimes takes many seconds to show its
  panel**: after running Edit Unit, the task panel can take seconds to
  appear, 29 s in one run during sh-021's manual QA on FreeCAD 1.1.1. It
  happens only sometimes, and the user has never seen it with another
  workbench. The `debug_log` timings for that run show every stage of this
  workbench's code finishing within 25 ms of the command, and the event
  loop running 13.5 ms after `showDialog`. The panel's first `Show` event
  then arrived 29 s later, with its first paint 13 ms after that, so the
  time is spent outside this workbench's code, before Qt shows the form.
  During the wait FreeCAD stayed responsive (the 3D view panned), and the
  whole Shelving menu was disabled, which FreeCAD does to commands while a
  task dialog is active, so the dialog was open but its form was not
  visible. Clicking around did not reveal it; it appeared on its own. Root
  cause unknown: some ancestor of the form stayed hidden for 29 s. The
  `debug_log` run now records the form's ancestors right after
  `showDialog` and again when the form is shown (`AncestorWatch` in
  `freecad/Shelving/editor/panel.py`). In a normal run on FreeCAD 1.0.0,
  the only hidden ancestor at that point is FreeCAD's own
  `Gui::TaskView::TaskBox` (hidden itself), which shows the form about 5
  ms later. A later run on the user's FreeCAD 1.1.1 shows their Tasks
  panel docked in FreeCAD's overlay mode: after `showDialog` the form's
  ancestors include `Gui::OverlayTabWidget 'OverlayRight'`, hidden itself
  with its current tab on Tasks, and every ancestor below it hidden. That
  run showed the form 0.2 s later, but an overlay panel can auto-hide until
  hovered or activated, which fits a dialog that is open yet unseen for a
  long time. The overlay is now the leading suspect, ahead of a stalled
  `TaskBox`. Fix: `ad hoc`, provisionally: the fix waits on a slow run's
  log confirming which ancestor held the form back, and, if it is the
  overlay, on whether the panel should raise it (for example through
  FreeCAD's overlay API) or document the setting.

- `bug-012` - **a typed size is refused on a scanned unit whose openings all
  differ in size**: on the Woodworking workbench's default Magic Start unit
  (`tests/freecad/fixtures/woodworking_magic_start_default.FCStd`), typing
  any size for a bay in Edit Unit fails with "Every opening in this row or
  column has a fixed size, leaving ... mm with nowhere to go". Found in the
  LinkGroup fix's spike. Root cause: `_recover_rules` in
  `freecad/Shelving/core/scan.py` gives a region `Fill` only when a sibling
  in its run has a matching size and `Fixed` otherwise, so the column's
  plinth gap (100 mm), lower bay (253 mm) and upper bay (353 mm) all come
  back `Fixed`. `set_size` then leaves no region to absorb the difference,
  and the solver refuses. Dragging the shelf fails too, as an overflow
  ("The fixed sizes add up to 30.0 mm more than the space available" for a
  30 mm drag), since the fixed bay above cannot shrink. Fix: `sh-XXX task`,
  because which openings should stay fixed and which should share leftover
  space on a unit nobody sized in this workbench (for example, everything
  but the region being sized, or the largest opening, or a prompt) is a
  product decision, and it changes the scan heuristic other units rely on.
