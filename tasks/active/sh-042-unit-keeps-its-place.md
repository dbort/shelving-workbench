---
id: sh-042
title: "A unit keeps its place in its container"
---

# sh-042: A unit keeps its place in its container

## Summary
A unit whose boards do not start at its container's origin jumps to the
origin the first time it is edited: every write lays the unit out from
(0, 0, 0). After this task every edit leaves the unit where its boards
are, and the 3D view's drawing and drags line up with an offset unit's
real boards. This is the ground sh-043's fixed point stands on, and it
fixes bug-018. Milestone M15.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] A container holding a four-board carcass whose minimum corner is at
      (100, -300, 50) in container coordinates, resized through
      `unit_ops.resize_unit` along each axis in turn, keeps that minimum
      corner at (100, -300, 50) within 1e-6 mm, and each board keeps its
      position along every axis the resize did not change.
- [ ] The same container edited through `Session` (a resize, a split, a
      typed size, a board drag) keeps its minimum corner, and a rescan of
      the written result reads back the same corner and the same tree.
- [ ] A unit scanned from boards at the container's origin writes exactly
      the placements it wrote before (the existing scan, write and
      fixture tests pass unchanged).
- [ ] In the view tier, Edit Unit on the offset container draws each
      opening's outline on its boards: every outline corner lies on the
      matching bay's bounds in document coordinates within 1e-6 mm, and a
      drag of a shelf's arrow by a given distance moves that shelf's
      document placement by the same distance.
- [ ] `unit_ops.create_unit` still builds its unit at the container's
      origin.
- [ ] `docs/scope-and-design.md` states that a unit's position comes from
      its boards, as its size does.

## Advice

CONSTRAINTS:
- Derive the position at every read and store nothing: the unit's
  position is its layout boards' minimum corner in container coordinates,
  measured over the same boards the unit's size is measured over, so size
  and position always describe one box. `scope-and-design.md` § "What is
  stored": every stored value is one a copied object can carry wrongly,
  and a user moving every board by hand must find the unit where they put
  it.
- Boards `scan` sets aside (`ScanResult.panels`), skipped parts, and
  objects left alone never count toward the position: they never count
  toward the size either.
- Carry the position on the `Unit` (a field in millimeters, default
  (0, 0, 0)) and have the solve place the root there, so `expand`,
  `write_container`, the editor's `ElevationFrame` and the drag mapping
  all read one value; a container-side offset added after the solve would
  need repeating at each of those. A default of the origin keeps every
  hand-built test unit and `create_unit` unchanged.
- The container's own `Placement` stays excluded from reading, as
  `container.py`'s module docstring states: the position is in container
  coordinates.
- `Session.resize`'s docstring promises the minimum corner stays put; it
  becomes true. Growth still goes to the maximum side: choosing the fixed
  point is sh-043.

FOLLOW FREECAD'S OWN TOOLS: a `Part::Box` grows from its `Placement` and
never moves when resized; a unit's boards do the same.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: precise types; `pyrefly check` clean.
- Shell stays simple: no shell.
- Users never read the log: nothing user-facing changes beyond the
  geometry staying put.

## Plan
- [ ] **Step 1** (`freecad/Shelving/core/layout.py`, `freecad/Shelving/core/scan.py`, `freecad/Shelving/core/solver.py`): `Unit` carries its position, `scan` sets it from the layout boards' minimum corner, and `solve` places the root there; core tests for an offset scan and solve.
- [ ] **Step 2** (`freecad/Shelving/container.py`, `freecad/Shelving/unit_ops.py`, `freecad/Shelving/editor/session.py`): Writes and rescans keep the position through every edit; FreeCAD-tier tests for the offset container's resizes and session edits.
- [ ] **Step 3** (`freecad/Shelving/editor/elevation.py`, `freecad/Shelving/editor/view_editor.py`): The elevation frame and the drag mapping start from the unit's position; view-tier tests for the outlines and a drag on the offset container.
- [ ] **Step 4** (`docs/scope-and-design.md`, `.claude/docs/bug-log.md`): The design prose; delete bug-018.

## Review log
