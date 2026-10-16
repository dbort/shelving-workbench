---
id: sh-041
title: "Padlocks lock and unlock openings in the view"
blocked_by: [sh-040]
---

# sh-041: Padlocks lock and unlock openings in the view

## Summary
Each opening's dimension in the 3D view gets a padlock, closed for a locked
opening and open for an unlocked one, and clicking it locks or unlocks the
opening without moving anything. A selected board held in place by locks
shows a padlock where its drag arrow would be, outlines the locked openings
holding it, and unlocks them with one click so the arrow appears. This puts
sh-038's locks in the user's hands; until now the only way to lock is to
type a size, and nothing unlocks. Milestone M14.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] In the view tier (sh-037), every opening's dimension shows a padlock
      just past its text along the dimension line: closed and in the View
      preference `ConstrainedDimColor` when the opening is locked, open and
      in `NonDrivingConstrDimColor` when unlocked. An unlocked opening
      alone in its row shows none. Each padlock's rectangle stays clear of
      its label's anchor point, and padlocks move with their labels when
      the camera moves and at every step of a drag.
- [ ] The padlock widgets are pooled: across a drag of many steps, the
      number of padlock widgets the editor has created never exceeds the
      largest number of dimensions shown at once.
- [ ] Clicking a padlock locks or unlocks its opening as one undo step
      ("Lock opening" or "Unlock opening"), every solved space is the same
      before and after, and the padlock shows the new state. Clicking the
      padlock of a row's last unlocked opening shows sh-038's refusal in
      the Notification Area and changes nothing.
- [ ] Typing a size into an unlocked opening's dimension closes its
      padlock.
- [ ] A selected board that sh-038's query says is held shows a closed
      padlock where its arrow would be, and no arrow, and the locked
      openings the query names are outlined in `ConstrainedDimColor`.
      Clicking that padlock unlocks exactly those openings as one undo
      step, after which the arrow shows on the board. A carcass board
      shows neither arrow nor padlock.
- [ ] With the opening between two shelves locked, dragging either
      shelf's arrow moves both shelves by the same distance and leaves the
      locked opening's size unchanged.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` gains a case for what no
      test asserts: whether the padlocks stay clear of the dimension text
      and legible at several zoom levels on a HiDPI screen, and whether
      there are too many of them to read the drawing.
- [ ] `docs/scope-and-design.md` describes locking and unlocking in the
      view.

## Advice

DECISIONS (user, 2026-10-13; `06d20ab:research/viewport-editing.md` §
"Locked and unlocked openings" on branch `research/viewport-editing`,
which stays until this task ships):
- **Every lockable opening shows its padlock, always,** so lock state is
  visible beside the dimension's color.
- **A padlock beside each dimension label toggles it.** Locking and
  unlocking never move anything (sh-038).
- **A held board shows a padlock where its arrow would be;** clicking it
  unlocks the nearest locked opening on each side that holds the board,
  in one undo step, and the arrow takes its place. Those openings are
  highlighted while the board is selected.
- **A carcass board shows neither** arrow nor padlock.
- **Weights never appear** in the interface; the padlock is the only way
  to unlock.
- **Evening out uneven unlocked openings is not in scope.** After drags
  the unlocked openings of a row can be uneven; the later spacing
  constraints design (`docs/roadmap.md` § Later) covers it.

FINDINGS from the spike (`06d20ab:freecad/Shelving/spikes/viewport_editor.py`,
§ Padlocks; checks in `06d20ab:research/spikes/drive_viewport_spike.py`):
- Each padlock is a borderless auto-raise `QToolButton`, 14 logical
  pixels, floating over the view as the add buttons do, from a pool
  reused across the rebuilds a drag runs at every step. Creating and
  destroying widgets per rebuild would churn at drag rate.
- Its icon is drawn with `QPainter` at the device pixel ratio: a body and
  a shackle, the shackle swung open for an unlocked opening, in the
  dimension's color.
- Placement: just past the text along the line. The spike estimated the
  text's width at 0.6 em per character of the label's string, with the
  em the Sketcher's dimension font size in logical pixels, plus a 4 px
  gap. A vertical dimension's text runs along its line, so its padlock
  sits above the text.
- The held board's padlock sits at the arrow's anchor, and its click
  unlocks every holder in one session write, so one undo step.
- Under FreeCAD's picking, Qt buttons over the view take their own
  clicks; nothing in Coin sees them.

CONSTRAINTS:
- Lock state comes from sh-038's core query and session calls only; the
  view keeps no lock state of its own.
- Refusals use the editor's existing Notification Area path.
- FreeCAD.app runs Python 3.11 while pixi runs 3.12: nothing 3.12-only;
  `override` from `freecad.Shelving.compat`.
- Tooltips and accessible names on every padlock ("Lock this opening",
  "Unlock this opening", "Unlock the openings holding this board"),
  with no grammar keyed to a number, so they stay localizable.

DECISION (user, 2026-10-16, during `/work`): undo steps keep the editor's
Title Case and never vary with a count: an opening's padlock makes "Lock
Opening" or "Unlock Opening", and a held board's padlock makes "Unlock
Board", whether it unlocks one opening or more. The Must Have's "Lock
opening" and "Unlock opening" mean these.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: precise types; `pyrefly check` clean.
- Shell stays simple: no shell.
- Users never read the log: the last-unlocked refusal reaches the user in
  the Notification Area.

## Plan
- [x] **Step 1** (`freecad/Shelving/editor/`): The padlock icon and the pooled padlock buttons placed past each lockable dimension's text, following the camera and every rebuild.
- [x] **Step 2** (`freecad/Shelving/editor/`): Clicks that lock and unlock through the session; the held board's padlock at the arrow's place, the holders' outline, and its unlock; no arrow or padlock on carcass boards.
- [x] **Step 3** (`tests/freecad_view/`): View-tier tests for every Must Have, including the locked-middle chain drag.
- [x] **Step 4** (`freecad/Shelving/qa/cases/30-editor.toml`, `docs/scope-and-design.md`): The legibility case and the design prose.

## Review log

### Round 1: REJECTED
- **F1: Pool test does not count created widgets** (`tests/freecad_view/test_padlocks.py:249`): only `len(editor.padlocks)` and a post-drag `findChildren` are checked, so a list rebuilt with fresh buttons each step could pass; collect the distinct buttons seen across steps and bound that.
- **F2: Units missing from pixel names** (`tests/freecad_view/test_padlocks.py:101`, `freecad/Shelving/editor/view_editor.py:946`): `_icon_pixel_alpha`'s `x`/`y` and `_move_to`'s `shift` hold logical pixels and need `_px`.
- **N1: Viewport mapping change unannounced** (`freecad/Shelving/editor/view_editor.py:956`): `_move_to` now maps from the viewport rather than the QGraphicsView, which also moves the field and add bar; correct, but unmentioned.
- **N2: QA `lock` step repeats a tested fact** (`freecad/Shelving/qa/cases/30-editor.toml:261`): ask only whether the closed padlock reads clearly on HiDPI.
- **N3: `Style.outline_rgb` docstring states rationale, not contract** (`freecad/Shelving/editor/overlay.py:72`).
- **N4: `settle()` runs twice in `unlock_holders`** (`freecad/Shelving/editor/session.py:555`).
