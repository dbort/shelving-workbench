---
id: sh-044
title: "A back follows the unit's boards"
blocked_by: [sh-042]
---

# sh-044: A back follows the unit's boards

## Summary
A back panel stays where it is today when the unit changes: deepen a
Magic Start cabinet and its 3 mm back ends up inside the carcass, widen it
and the back is too narrow. After this task a back moves and resizes with
the boards around it on every edit, whether it is an overlay back proud
behind the carcass or one set within it, and Edit Unit's list says which
panels it found as backs. Doors and unreadable parts still stay put, and
the unit's Width, Height and Depth still measure the carcass without its
back. Milestone M11.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] On `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`,
      through `unit_ops.resize_unit` and through `Session.resize`: after a
      depth change the back keeps its 3 mm thickness and its front face
      lies on the sides' new rear face; after a width change it spans the
      outer faces of both sides; after a height change its top edge lies
      on the sides' new top and its bottom edge on the floor's underside.
      Each within 1e-6 mm, the back's Placement rotation unchanged.
- [x] On the same fixture, a `Session` edit that moves the floor moves the
      back's bottom edge by the same distance and leaves its top edge.
- [x] A back edge that lines up with no board face keeps its distance to
      the unit's outer face on that side through a resize; an edit that
      removes the board an edge followed (a `Session.merge` of the divider
      a per-opening back's edge lies on) succeeds, and that edge then keeps
      the distance it had at the read to the unit's outer face.
- [x] A back that is not a plain box (a `Part::Cut` of a box, or any shape
      `read_container` reads as irregular) moves with its low corner
      following its low edges and keeps its shape exactly (`Shape.Volume`
      and bounding-box size unchanged within 1e-6).
- [x] A panel thin through the depth that is not a back (proud of the
      front at stock thickness, a door) and every part `read_container`
      skips keep their Placement and size through every resize and session
      edit, and stay in `WriteResult.left_alone`.
- [x] With the unit's facing unknown and no panel giving it, no panel
      moves.
- [x] A back is never given board properties (`has_board_properties`
      stays false), is never deleted by a write, and keeps its material,
      color and Label untouched, and the write changes nothing on it but
      Placement and, for a plain box, Length/Width/Height.
- [x] One Undo after a session resize restores the back's Placement and
      size together with the boards'; Redo reapplies both.
- [x] `rescan_unit` straight after any write moves no back by more than
      1e-6 mm: the written result reads back as the same backs following
      the same faces.
- [x] `unit_ops.unit_size_mm` on the Magic Start fixture still returns its
      carcass size, the back excluded.
- [x] Edit Unit's list of objects the workbench did not create shows each
      back with a reason saying it follows the unit's boards, still with a
      check box for Delete Selected; other entries keep their reasons, and
      the list's explanation no longer says every listed object is left
      alone.
- [x] `docs/scope-and-design.md` describes how a back is recognized and
      what each of its edges follows.

## Advice

DECISIONS (user, 2026-10-16, `/new-task`):
- **Existing backs follow; nothing adds one.** A back the unit already has
  moves and resizes with the carcass whatever its treatment. Adding or
  removing a back, choosing its treatment and its material are later M11
  work.
- **Each edge follows the board face it meets.** At every read, each of a
  back's four elevation edges is matched to the board face it lines up
  with (Magic Start's bottom edge to the floor's underside, its side edges
  to the sides' outer faces), as a Part attachment follows its support's
  face; an edge meeting no board face follows the unit's outer face on
  that side at the distance it has from it.
- **A lost face falls to the outer face.** An edit removing the board an
  edge follows goes ahead, and the edge keeps the distance it had at the
  read to the unit's outer face. The next read matches it afresh.
- **The unit's size stays the carcass's,** backs excluded, as sh-032
  decided for Resize Unit and as sh-043's fixed point measures it.
- **Backs only.** A panel set within the carcass's depth span, or proud
  behind it and thinner than the stock, is a back. A stock-thick panel
  proud of the front reads as a door and stays left alone: a door belongs
  to one opening, and following the unit's outline would misplace it
  after a split.
- **The list names backs as following.** Edit Unit's list of objects the
  workbench did not create keeps a row for each back, with a reason
  saying it follows the unit's boards, so the user sees which panels were
  recognized; Delete Selected still deletes one.
- **An irregular back moves and keeps its shape,** as a pinned board is
  carried and positioned but never reshaped.

CONSTRAINTS:
- Derive everything at each read and store nothing on the container:
  `scope-and-design.md` § "What is stored", and a back moved by hand must
  be followed from where the user put it.
- Recognize backs with the scan's own facing logic (`infer_facing`,
  `_panel_vote`, the half-stock backing threshold in `core/scan.py`), so a
  panel that gave the facing and a panel that follows as a back never
  disagree. With the facing unknown, nothing is a back: front and rear
  cannot be told apart.
- Along the depth axis a back keeps its thickness and its distance from
  the carcass's rear face; only the four elevation edges match board
  faces. A face match is within `snap_mm` and needs the board to overlap
  the back along the edge's other elevation axis. When several boards
  match one edge, any choice gives the same position at the read; prefer
  a face across a board's thickness (the floor's underside) over a
  board's end, then the lowest id, so the choice is deterministic.
- Carry the backs on the `Unit` (object name, irregular flag, each edge's
  followed board id and face or its outer-face distance, the depth
  distance), so every edit's `dataclasses.replace` keeps them and
  `write_container` reads one value, as sh-042 carries the position. A
  board id an edit renames (`renamed_board_ids`, `WriteResult.id_renames`)
  is renamed in the backs too.
- `ScanResult.panels` keeps listing every panel set aside from the tree;
  backs are a subset of it, so `test_scan.py`'s panel assertions hold.
- Never tag a back with board properties: `write_container` deletes a
  tagged object the tree does not name. Report the backs a write placed
  apart from `WriteResult.left_alone`, since every name in that list is
  one the write left untouched.
- Write only Placement and, for a plain box, Length/Width/Height, the way
  `_write_geometry` writes a board. When following would give a back a
  non-positive size, refuse the edit through the session's existing
  `EditFailure` path, naming the back, before anything is written.
- `test_write.py::test_left_alone_objects_are_never_touched` adds a 5 mm
  panel at the front of a starter unit whose facing is unknown; the panel
  gives the facing and becomes its back. Keep the test's intent (a panel
  that is not a back is left alone) by making that panel a stock-thick
  one proud of the front, and add the back case separately.
- UI text stays localizable: no wording keyed to how many backs there are.

FOLLOW FREECAD'S OWN TOOLS: Part's attachment (`AttachExtension`) is the
precedent for a solid following a face of another; Woodworking's Magic
Start builds its back as a separate thin board over the carcass's rear
edges, which is the shape this task reads. No comparable tool stores the
link here, and the store-nothing rule above is why this one does not
either.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: precise types (a `Literal` or enum for the face an edge
  follows); `pyrefly check` clean.
- Shell stays simple: no shell.
- Users never read the log: the list row is where a user sees which
  panels follow; a refused edit reports through the panel's existing
  error path.

MANUAL QA: none. Every behavior here is a Placement or a list row a test
asserts, and the editor's live drag writes the real boards, so a back
follows during a drag through the same write the tests exercise.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/layout.py`, `freecad/Shelving/core/scan.py`): A back type on `Unit`, defaulting to none; `scan` recognizes backs among the panels and records what each edge follows; core tests on `real_magicstart_f1.boxes.json` and hand-built overlay, captured and per-opening backs, with facing unknown, and with a door.
- [x] **Step 2** (`freecad/Shelving/core/expand.py` or a new `freecad/Shelving/core/backs.py`): Each back's placement and size from the solved boards, with the outer-face fallback for a missing board and the refusal for a non-positive size; core tests for each edge kind, a renamed board, a removed board.
- [x] **Step 3** (`freecad/Shelving/container.py`, `freecad/Shelving/unit_ops.py`, `freecad/Shelving/editor/session.py`): `write_container` writes the backs and reports them apart from `left_alone`; the session renames their board ids and lists them with the following reason; FreeCAD-tier tests on the Magic Start fixture for resizes, the floor move, Undo/Redo, rescan, the irregular back, and the updated `test_write.py` case.
- [x] **Step 4** (`freecad/Shelving/editor/panel.py`): The list's explanation and the back's row; a GUI-tier test for the row and Delete Selected on a back.
- [x] **Step 5** (`docs/scope-and-design.md`): How a back is recognized and what its edges follow.

## Review log
