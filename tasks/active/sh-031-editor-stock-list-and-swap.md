---
id: sh-031
title: "The editor's stock list and stock swap"
blocked_by: [sh-030, sh-032]
---

# sh-031: The editor's stock list and stock swap

## Summary
The Edit Unit panel lists the stocks the unit's boards are made of: each
distinct combination of thickness, FreeCAD material and color, with how many
boards use it. Clicking a stock selects its boards and Ctrl-click adds or
removes single boards; "Change stock…" then changes the selection's thickness,
material or color together. That replaces the catalog's job of swapping
materials, and puts it in the editor, scoped to one unit and undone by Cancel.

## Must Have
- [ ] `pixi run tests` green.
- [ ] A core edit sets the run-axis thickness of a given set of boards and
      returns the new `Unit`. It refuses an unknown id, a non-board id and a
      non-positive thickness. Core tests on one unit assert:
      - the unit's outside size is unchanged;
      - a `Basis.WITH_NEXT` region's next board keeps its position, and a
        `Basis.CLEAR` region's next board moves;
      - a thickness that cannot fit raises the solver's error.
- [ ] The session lists the unit's stock groups, one per distinct (thickness,
      `ShapeMaterial` name, dominant color), each with its board ids, ordered
      by board count, most first. Left-alone objects are never in a group.
      Headless, where color is unknown, the grouping uses thickness and
      material only. Asserted on a copy of
      `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`: one group
      holding the five layout boards, with the back board in none.
- [ ] A session stock swap applies to the selected boards, inside the session
      transaction, any combination of: a thickness, a material from FreeCAD's
      library (by UUID, set as `ShapeMaterial`), and a color. Asserted
      headless on the Magic Start copy:
      - after a swap of the shelf to 12 mm and another material, the groups
        are one of four boards and one of the shelf;
      - a swap that cannot fit returns a failure and changes no board;
      - Cancel restores every board's geometry and `ShapeMaterial`.
- [ ] In `tests/freecad_gui/`:
      - a material swap with no explicit color repaints the boards in the
        material's appearance diffuse color;
      - an explicit color wins over the material's;
      - after a swap every face of each board has the same color, so
        per-face colors are replaced.
- [ ] In `tests/freecad_gui/`, the panel:
      - clicking a stock row selects exactly that group's boards;
      - Ctrl-click adds a board to the selection and removes a selected one;
      - while more than one item is selected, Add Divider, Add Shelf, Delete,
        Size and the basis control are disabled, and Change stock… is enabled;
      - a plain click returns to single selection.
- [ ] A swap never changes a board's `Grain`. Asserted headless.
- [ ] QA cases in `freecad/Shelving/qa/cases/` cover:
      - selecting by stock row and by Ctrl-click;
      - a material swap recoloring boards;
      - a thickness swap in which a spacing-based shelf holds and a
        clear-based one moves, the case sh-030 removed.
- [ ] `pyrefly check` clean.

## Advice

DECISIONS (user, 2026-10-09, after the catalog-removal interview):
- **A stock** is the triple (thickness, `ShapeMaterial` name, dominant
  color). A board's dominant color is its most common face color. The list
  is derived from the unit's boards every time, never stored.
- **Selection:** clicking a stock row selects all of that group's boards;
  Ctrl-click on a board in the elevation adds or removes it. Do not bind
  double-click: the user is reserving it for a later "change the spacing of
  every sibling" gesture.
- **Single-item controls** (Add Divider, Add Shelf, Delete, Size, basis) act
  only when exactly one item is selected, and are disabled otherwise. A plain
  click returns to single selection.
- **The swap UI** is "Change stock…", enabled with one or more boards
  selected. It opens a small dialog with three optional fields: thickness, a
  quantity input like the size field; material; and color. A blank field
  leaves that property unchanged.
- **Materials** come from FreeCAD's material library through the `Materials`
  module (`Materials.MaterialManager().Materials`, keyed by UUID; verified on
  1.1.3 with 200 materials including "Wood"), never from scanning folders. It
  includes the user's own library, which is where Woodworking's
  `panelMaterial` looks.
- **Color:** picking a material repaints the boards in that material's
  appearance `DiffuseColor`, as Woodworking's `panelMaterial` does, unless the
  same swap also sets a color, which wins. Every face is repainted, replacing
  per-face colors.
- **Thickness:** the unit's outside size holds, and a spacing keeps the board
  after it in place while a clear opening lets it move, as stock changes
  behaved under the old Reflow All. A change that cannot fit is refused and
  changes nothing.
- **Scope:** this unit only, inside the session's one transaction, so Cancel
  undoes it. Left-alone objects are never listed or changed.
- **Grain** is never touched by a swap.

LAYERING, as in sh-020 and sh-021:
- The thickness edit and the grouping key are decided in the core and tested
  in the fast suite.
- The session owns the document, the transaction, `ShapeMaterial`, and the
  appearance through `ViewObject`.
- The panel only displays and dispatches.

Color exists only with a GUI (`.claude/docs/freecad-notes.md`), so headless
grouping and swaps work on thickness and material alone, and every color
assertion belongs in `tests/freecad_gui/`.

DEPENDS ON sh-030: a board's thickness is its own geometry, with no catalog
and no material id, and the session reads no catalog. Plan against the code
as sh-030 leaves it.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: no bare `Any`, no bare
containers in signatures; the `Materials` module, `ShapeMaterial` and
`ShapeAppearance` go through typed Protocols, since `freecad-stubs` may not
cover them; `pyrefly check` clean. Shell stays simple: this task adds no
shell.

## Plan
- [ ] **Step 1** (`freecad/Shelving/core/`): The edit that sets the run-axis thickness of a set of boards, plus the pure stock-grouping function over (thickness, material name, color or `None`) records, with core tests.
- [ ] **Step 2** (`freecad/Shelving/editor/session.py`): Multi-board selection alongside the existing single selection, the stock groups (reading `ShapeMaterial` and, with a GUI, the dominant face color), and the stock swap (thickness through the core edit and the write path; `ShapeMaterial` from a library UUID; color repainting every face).
- [ ] **Step 3** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/editor/scene.py`): The Stock section with its rows, Ctrl-click in the view, selection highlighting for several boards, single-item controls disabled during a multi-selection, and the "Change stock…" dialog with its three optional fields and FreeCAD's material list.
- [ ] **Step 4** (`tests/freecad/`, `tests/freecad_gui/`): The headless and GUI Must Have tests.
- [ ] **Step 5** (`freecad/Shelving/qa/cases/`, `README.md`): The QA cases, and glossary entries for a stock and the stock swap.

## Review log
