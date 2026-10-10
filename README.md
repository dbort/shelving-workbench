# Shelving Workbench

[![CI](https://github.com/dbort/shelving-workbench/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dbort/shelving-workbench/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/dbort/shelving-workbench/badge)](https://scorecard.dev/viewer/?uri=github.com/dbort/shelving-workbench)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![FreeCAD 1.1](https://img.shields.io/badge/FreeCAD-1.1-blue.svg)](https://www.freecad.org)

A FreeCAD 1.1 workbench for parametric shelving. A unit is designed as a flat
front elevation and expands into individually editable 3D board solids; editing
the elevation reflows the 3D. The layout math lives in a pure-Python core
(`freecad.Shelving.core`) that never imports FreeCAD, so it is testable
without a GUI.
See [`docs/scope-and-design.md`](docs/scope-and-design.md) for what the project
is for and how it is built, and [`docs/roadmap.md`](docs/roadmap.md) for the
milestone breakdown. [`docs/architecture.md`](docs/architecture.md) describes
the pre-M4 design; `scope-and-design.md` is the design of record.

## Setup

### Recommended: `tools/install-deps.sh`

```sh
tools/install-deps.sh
```

The script is idempotent. It provisions the pixi environment: the dev toolchain
plus FreeCAD 1.1, pinned by `pixi.lock`. If `pixi` is not already on `PATH`, the
script downloads a pinned release for the host architecture, verifies its
published `.sha256`, installs it into `~/.local/bin`, and adds that directory to
`~/.bashrc` and `~/.profile`. See the [pixi documentation](https://pixi.sh) for
the tool itself.

To install pixi yourself instead, follow its docs, then run `pixi install` in
the checkout.

If the script just installed pixi, open a new shell (or `source ~/.profile`)
so `~/.local/bin` is on `PATH`. `pixi install` installs the project itself
editable (`pixi.toml`'s `[pypi-dependencies]`), so `import
freecad.Shelving.core` resolves to the checkout under `pixi run` / `pixi
shell` with no separate packaging step: the editable install's `.pth` file
puts the repo root on `sys.path` at interpreter startup, before pytest's
own collection or `freecadcmd`'s internal FreeCAD imports run.

## Tests

`pixi run tests` is the pre-merge gate and what CI runs. In one pass it covers:

- static analysis: `ruff` lint and format, and a strict `mypy` type check;
- the `freecad.Shelving.core` unit suite;
- the `pixi.lock` path guard;
- the workflow-hardening lint over `.github/workflows/` (see
  [`docs/github-actions-hardening.md`](docs/github-actions-hardening.md));
- a `freecadcmd` check that the workbench imports through FreeCAD's own
  startup;
- the headless FreeCAD suite in `tests/freecad/`, with FreeCAD imported from
  plain pytest;
- the GUI suite in `tests/freecad_gui/`, with FreeCAD's GUI started on Qt's
  offscreen platform, since the panel's quantity field exists only there.

Both FreeCAD suites run against throwaway FreeCAD settings, so they never
read or change yours. Each needs a pytest run of its own, for example
`pixi run pytest tests/freecad_gui -k drag`; any other run, a bare
`pixi run pytest` included, skips them and says so in its summary.

It runs inside the pixi environment, which supplies every tool including
FreeCAD. To run only the workflow lint, use `bash tools/lint-workflows.sh` from
inside `pixi shell`. For offline work, `pixi run tests -- --offline` skips the
checks that need network access.

## Glossary

The layout vocabulary and how each term maps onto the code in
`freecad.Shelving.core`, which follows
[`docs/scope-and-design.md`](docs/scope-and-design.md).

- **Unit**: a shelving unit. `Unit` in `freecad.Shelving.core.layout` holds
  the outer `size_mm`, a root `Region`, and a persistent `id`.
  There is no distinguished shell: the outermost boards of the outermost
  divisions are the shell.
- **Region**: `Bay | Void | Division`, one node of the tree. Every region
  carries a persistent `id`; `Bay` and `Void` and `Division` also carry the
  `SizeRule` their parent division sizes them by (unused and unvalidated on
  the root, which has no parent).
- **Bay**: an enclosed compartment: open, and part of the unit.
- **Void**: space inside the unit's bounding box that is not part of the
  unit. What makes an outline stepped. A `Void` holds no boards and is not a
  compartment.
- **Division**: a region cut into an ordered run of boards and sub-regions
  along one `Axis`. Items run in order and need not alternate, so two
  adjacent `Board` items are two boards face to face.
- **Item**: `Board | Region`, one entry in a `Division`'s `items` list.
- **Board**: one physical member of the finished unit; user-facing
  documentation calls the same thing a panel. `Board.role` is a free-form
  string set by the caller; there is no closed role enum, because a stepped
  outline can have several tops and none of them is *the* top.
  `Board.thickness_mm` is the board's own thickness: for a scanned board,
  its slot in the scan's snapped grid, so a run always adds up exactly.
- **Insets**: how far a `Board` is set back from its region on each of six
  faces (`x_min_mm` / `x_max_mm` / `y_min_mm` / `y_max_mm` / `z_min_mm` /
  `z_max_mm`, all defaulting to `0.0`). The pair on the board's own division
  axis is ignored: a board always fills that axis with its own thickness.
- **Axis**: `X`, `Y`, or `Z`, which of a unit's three dimensions a `Division`
  cuts along.
- **Size rule**: `SizeRule = Fixed | Weighted | Fill`, how a division sizes
  one item along its axis. `Fixed` takes an exact `size_mm` (see `Basis`
  below); `Weighted` takes a share of slack proportional to `weight`; `Fill`
  is shorthand for `Weighted(1.0)`.
- **Basis**: what a `Fixed` rule's `size_mm` measures. `CLEAR` is the
  region's own extent along the axis. `WITH_NEXT` is the region plus the
  item immediately after it in the run, the way a shelf spacing is usually
  quoted top face to top face; the solver resolves it to a clear size before
  distributing.
- **Local coordinate frame**: origin at the unit's front-bottom-left corner,
  `+X` right (width), `+Y` back (depth), `+Z` up (height). A board's
  placement in that frame is its minimum corner; its size is its extent
  along each axis. All lengths are float millimetres.
- **depth axis**: the `Axis` a scan treats as running front to back, detected
  as the bounding-box axis with the smallest span unless given explicitly.
  Scanning divides only along the other two axes, never along the depth
  axis.
- **facing**: which end of the depth axis is the front, recorded on
  `Unit.front_at_min` (`True` at the axis's minimum end, `False` at its
  maximum, `None` when undetermined). Affects presentation only: which end
  of a division reads as left, never the tree `scan` builds.
- **snap tolerance**: `snap_mm`, a `scan` parameter defaulting to 0.5 mm.
  Edges within this distance of each other collapse to one grid line, wide
  enough to absorb the tens-of-microns disagreement real exported geometry
  has at a joint.
- **joint clearance**: `clearance_mm`, a `scan` parameter defaulting to
  3.0 mm. A board end may stop up to this far short of the region edge it
  spans to without splitting that edge into its own compartment.
- **the cut rule**: a cut is any line no board crosses, not a line some one
  board spans, so two boards meeting face to face (an abutting seam, a
  framed wall's double top plate) cut just as cleanly as a single board
  would.
- **the container's own frame**: how a scanned container's boards are
  placed. Nested container placements between the selected container and
  each part compose, but the selected container's own placement is
  excluded, so a unit reads identically wherever it sits in the document.
- **Shelving_Scan**: the command id that reads the selected container,
  scans it, and prints the report, or refuses and selects the objects that
  defeated it.
- **Shelving_ExportBoxes**: the command id that writes a selected
  container's boards and unreadable parts to JSON without scanning, so a
  unit `Shelving_Scan` refuses can still be captured.
- **stock**: a board's thickness, `ShapeMaterial`, appearance, and grain.
  The workbench keeps the last three where the Woodworking workbench does:
  FreeCAD's `ShapeMaterial`, the view's `ShapeAppearance`, and a `Grain`
  string list in property group `Woodworking`, one entry per face. A write
  never changes them on a board that already exists.
- **carcass board**: a board with, along its run, no `Bay` between one of
  its faces and the unit's edge, only `Void`, other boards, or nothing.
  `freecad.Shelving.core.stock.is_carcass` decides it from the tree, so a
  floor raised over a plinth gap is carcass.
- **source board**: the existing board a board the editor creates copies
  its stock from, chosen by `freecad.Shelving.core.stock.source_board`
  among boards with the same thin axis: an interior board in the new
  board's own run, then the nearest interior board, then the nearest
  carcass board; failing all three, the nearest board of any kind. The new
  `Board` carries its id as `stock_from`.
- **the core edit layer**: `freecad.Shelving.core.edit`. `split_region`,
  `merge_at`, `set_size`, `set_basis`, and `move_board` rebuild a `Unit`'s
  tree, `Unit` in, `Unit` out, never mutating the argument; `EditError` is
  the refusal each raises, carrying the offending region or board id.
  `measure` reports a region's clear size, its spacing, and its basis for
  display. No Qt, no FreeCAD, tested in the fast suite.
- **the scene layer**: `freecad.Shelving.editor.scene`. `build_scene` draws a
  `QGraphicsScene` elevation from a `Unit` and its solved spaces, one item
  per region and per board, each tagged with its id, plus a dimension per
  region; `hit_test` answers what is at a scene point, and
  `elevation_point_mm` maps a scene point back to the unit's frame. Knows
  nothing about documents or transactions.
- **measurement basis**: the editor's name for a `Fixed` rule's `Basis`,
  chosen per dimension: **Clear opening** (`CLEAR`) or **Spacing** (`WITH_NEXT`,
  through the next board). Changing it moves nothing: `set_basis` restates
  the number so the layout solves identically. It matters when stock
  thickness changes: a spacing holds the board after it in place, a clear
  opening moves it. A dimension is drawn with witness lines on the faces its
  basis measures, so a spacing visibly crosses its board.
- **the drag rule**: dragging a board resizes the region immediately before
  it in its run and changes only that region's number, never its basis. A
  region that was sharing leftover space becomes a clear opening.
- **the session/panel layer**: `freecad.Shelving.editor.session` and
  `panel.py`. The session owns the document, the one transaction the whole
  editing session shares, and the write path; the panel is the Qt task
  dialog wiring controls to it, holding only input handling, which
  `tests/freecad_gui/test_panel.py` covers under the offscreen GUI.
- **Session**: `freecad.Shelving.editor.session.Session`. Reads a container
  once, then answers `can_split`/`can_merge` for the current selection and
  applies `split`/`merge`, `set_size`/`set_basis`, and a drag
  (`begin_drag`/`drag_to`/`end_drag`) through the core edit layer,
  re-solving and writing through the real write path on each accepted edit;
  `open`, `commit`, and `cancel` bound the one transaction. `open` also
  creates the temporary probe object the dimension field binds to so it can
  resolve a `VarSet` name, and `commit` deletes it. `left_alone` lists the
  container's objects this workbench did not write, each with its reason;
  `delete_untagged` deletes named ones inside the transaction. A rejected
  edit returns an `EditFailure` (a message and the offending id) rather than
  raising, and changes nothing.
- **Shelving_EditUnit**: the command id that opens the elevation editor task
  panel on the unit the selection names: the unit's container, or any
  objects inside it, all from the same unit. Disabled for any other
  selection.
- **debug_log**: `freecad.Shelving.debug_log`, the workbench's verbose
  diagnostic output in the Report view, on by default. Turn it off from the
  Python console with `from freecad.Shelving import debug_log;
  debug_log.enabled = False`. Each command run it covers is bracketed by
  `===== BEGIN` and `===== END` lines, and every line in between carries
  the same `#N` run id.
