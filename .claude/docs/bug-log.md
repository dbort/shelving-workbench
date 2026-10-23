---
next_id: bug-022
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
  `AncestorWatch` in `editor/panel.py` logs the hidden ancestors. sh-041's
  manual QA on 1.1.4 logged the form's first `Show` 15.2 s after
  `showDialog`, with `OverlayRight` reported as hidden itself until then.
  Fix:
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
- `bug-017` - **a nested opening's dimension sits outside the longer one
  holding it**: in a four-board unit with a shelf in the opening, a shelf
  in the lower opening and a divider in the middle one, the middle
  opening's height is drawn left of the unit's full interior height, so
  the shorter dimension is the outer one. `_Planner.labels` in
  `editor/elevation.py` claims outer rows with `_outer_row` in `_walk`'s
  pre-order, so a containing division takes row 1 before any division
  nested in it; drawing convention puts shorter dimensions nearer the part.
  Found in sh-041's manual QA; `main` behaves the same, since sh-041 left
  the row logic alone. Fix: `ad hoc`. Claiming rows innermost or shortest
  span first is local to the planner, and the convention it follows is
  not in question.
- `bug-019` - **a typed opening size under about 3.5 mm is lost on Undo,
  Redo or reopening**: typing 2 mm into a bay's size field is accepted and
  drawn, but Undo then Redo reads the column back as one bay, the 2 mm
  opening gone. The editor rescans the boards on every read-back, and the
  scanner drops board faces within its 3 mm clearance plus 0.5 mm snap of
  each other. `set_size` in `core/edit.py` accepts any positive size.
  Found while making a drag stop at `MIN_DRAG_GAP_MM` instead of refusing,
  and reproduced headless. Fix: `ad hoc`: refuse a typed size below that
  minimum, through the size field's existing refusal.
- `bug-021` - **a copied unit loses its locks**: copy a unit with its
  boards, grow both 200 mm taller, and the original's opening locked at
  200 mm keeps its size while the copy's takes a share (247 mm). The rule
  record keys each opening by its bounding boards' `Name`s, a copy's
  boards get new `Name`s, and nothing translates the copied record
  through the `ShelvingBornAs` each copied board carries. Found while
  planning M18, and reproduced headless on FreeCAD 1.1.3 with
  `doc.copyObject(container, True)`. Fix: `sh-XXX task`. Which copies
  qualify (Copy and Paste, a clone, a Link) and how a record maps onto
  them are design questions, and M18's constraint record keys the same
  way.
