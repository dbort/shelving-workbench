---
next_id: bug-017
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
- `bug-005` - **after deleting a divider beside a stack of shelves, a
  full-height divider cannot be added back**: the whole-width region is a
  `Division`, and `Session.can_split` and `core.edit.split_region` act only
  on a selected `Bay`. Found in sh-020's manual QA. Fix: `sh-XXX task`.
  It needs an edit that splits a `Division` across its cross axis and a
  way to select a region with no area of its own, both design questions.
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
  can auto-hide until hovered, so it is the leading suspect. A fresh
  FreeCAD 1.1.3 profile docks Tasks there too: under Xvfb (sh-037) the
  dialog's buttons stay hidden inside `OverlayRight` until hovered.
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
- `bug-016` - **Edit Unit once refused with "Internal C++ object
  (PySide6.QtWidgets.QGraphicsView) already deleted"**: seen three times
  running in sh-040's manual QA on FreeCAD 1.1.4 for macOS, in the HiDPI
  case after earlier cases had opened and closed editors in other
  documents. The panel built, then building the in-view editor failed as
  soon as it used the widget `view.graphicsView()` returned
  (`editor/view_editor.py`), the one place besides `commands/edit_unit.py`
  that touches a `QGraphicsView`. A stale PySide wrapper for a destroyed
  view is the leading suspect. It did not reproduce under Xvfb. The
  refusal now logs its traceback to the Report view: capture that the
  next time it happens. Fix: `sh-XXX task` once the traceback shows the
  cause.
