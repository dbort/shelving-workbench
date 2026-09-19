# Shelving Workbench

[![CI](https://github.com/dbort/shelving-workbench/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dbort/shelving-workbench/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/dbort/shelving-workbench/badge)](https://scorecard.dev/viewer/?uri=github.com/dbort/shelving-workbench)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![FreeCAD 1.0](https://img.shields.io/badge/FreeCAD-1.0-blue.svg)](https://www.freecad.org)

A FreeCAD 1.0 workbench for parametric shelving. A unit is designed as a flat
front elevation and expands into individually editable 3D plank solids; editing
the elevation reflows the 3D. The layout math lives in a pure-Python core
(`shelving_core`) that never imports FreeCAD, so it is testable without a GUI.
See [`docs/scope-and-design.md`](docs/scope-and-design.md) for what the project
is for and how it is built, and [`docs/roadmap.md`](docs/roadmap.md) for the
milestone breakdown. [`docs/architecture.md`](docs/architecture.md) describes
the pre-M4 design; `scope-and-design.md` is the design of record.

To eyeball a solved layout, run `pixi run demo`: it builds a sample stepped
unit, solves the region tree, and prints the catalog, the solved `Space` for
every region, and the expanded board table.

## Setup

### Recommended: `tools/install-deps.sh`

```sh
tools/install-deps.sh
```

The script is idempotent. It provisions the pixi environment: the dev toolchain
plus FreeCAD 1.0, pinned by `pixi.lock`. If `pixi` is not already on `PATH`, the
script downloads a pinned release for the host architecture, verifies its
published `.sha256`, installs it into `~/.local/bin`, and adds that directory to
`~/.bashrc` and `~/.profile`. See the [pixi documentation](https://pixi.sh) for
the tool itself.

To install pixi yourself instead, follow its docs, then run `pixi install` in
the checkout.

If the script just installed pixi, open a new shell (or `source ~/.profile`)
so `~/.local/bin` is on `PATH`. `pixi run` and `pixi shell` then work from the
checkout; both put `shelving_core` on the import path for scripts such as
`tools/layout_demo.py`, which carry no `sys.path` shim of their own.

## Tests

`pixi run tests` is the pre-merge gate and what CI runs. In one pass it covers:

- static analysis: `ruff` lint and format, and a strict `mypy` type check;
- the `shelving_core` unit suite;
- repository-consistency checks: the `pixi.lock` path guard and the
  vendored-core drift check;
- the workflow-hardening lint over `.github/workflows/` (see
  [`docs/github-actions-hardening.md`](docs/github-actions-hardening.md));
- a headless `freecadcmd` workbench import smoke.

It runs inside the pixi environment, which supplies every tool including
FreeCAD. To run only the workflow lint, use `bash tools/lint-workflows.sh` from
inside `pixi shell`. For offline work, `pixi run tests -- --offline` skips the
checks that need network access.

## Glossary

The layout vocabulary and how each term maps onto the code in `shelving_core`,
which follows [`docs/scope-and-design.md`](docs/scope-and-design.md).

- **Unit**: a shelving unit. `Unit` in `shelving_core.layout` holds the outer
  `size_mm` (a `Vec3`), a `default_material`, a root `Region`, and a
  persistent `id`. There is no distinguished shell: the outermost boards of
  the outermost divisions are the shell.
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
- **Board**: one physical member of the finished unit. `expand` emits one
  `BoardSpec` per `Board`; user-facing documentation calls the same thing a
  panel. `Board.role` is a free-form string set by the caller; there is no
  closed role enum, because a stepped outline can have several tops and none
  of them is *the* top.
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
- **Catalog**: the material table. `Catalog` in `shelving_core.materials` maps
  a `MaterialId` to a `MaterialEntry`.
- **Material entry**: one stock record. `MaterialEntry` carries `id`, `name`,
  `thickness_mm`, `material_type`, and an optional `nominal_thickness` label.
  The solver resolves a `MaterialId` to `thickness_mm`.
- **MaterialId**: a `NewType('MaterialId', str)`. `Unit.default_material`
  applies to any `Board` that sets no `material` of its own.
- **BoardSpec**: the output record of `expand`, a frozen dataclass
  `(node_id, role, size, placement, material)`. `node_id` is the owning
  `Board.id`. `size` and `placement` are `Vec3`. There is no grain field yet.
- **Vec3**: a frozen dataclass `(x_mm, y_mm, z_mm)` in `shelving_core.geometry`,
  used for a point or an extent.
- **Space**: a frozen dataclass in `shelving_core.geometry`, an axis-aligned
  box as a minimum corner `origin` (`Vec3`) plus an extent `size` (`Vec3`).
- **Local coordinate frame**: origin at the unit's front-bottom-left corner,
  `+X` right (width), `+Y` back (depth), `+Z` up (height). A
  `BoardSpec.placement` is the board's minimum corner in that frame; `size`
  is its extent along each axis. All lengths are float millimetres.
- **distribute**: `distribute(axis_span_mm, rules, divider_thicknesses_mm,
  node_id=...)` in `shelving_core.solver`. One opening size per rule, sharing
  slack by fixed / weighted / fill; it knows nothing about regions, boards,
  or axes, and does not resolve `Basis`.
- **solve**: `solve(unit, catalog)` in `shelving_core.solver`. Walks the
  region tree from the unit's outer `Space`, returning one `Space` per region
  and board id.
- **expand**: `expand(unit, catalog)` in `shelving_core.expand`. Calls
  `solve`, then returns the `list[BoardSpec]` for every `Board` in the tree,
  in pre-order. Like the solver, it has no FreeCAD dependency and produces
  plain data.
- **Box**: the input record `scan` reads, a frozen dataclass `(name,
  corner_mm, size_mm)` in `shelving_core.scan`, both `Vec3`. One axis-aligned
  solid: a document object's name, minimum corner, and extent.
- **Skipped**: a part `scan` could not read as a board, carried through
  rather than dropped: a frozen dataclass `(name, label, type, reason)`. A
  dropped board does not fail a scan, it makes an enclosed bay read as open.
- **ScanError**: `scan`'s refusal, a `ValueError` subclass carrying the
  offending object names in an `objects` attribute.
- **ScanResult**: `scan`'s return value, a frozen dataclass `(unit, panels,
  skipped, facing_evidence, thicknesses_mm)`. `panels` are the boards thin
  through the depth axis, set aside rather than placed; `thicknesses_mm` is
  every distinct board thickness found.
- **FacingEvidence**: what settled which way a unit faces: `GIVEN` (the
  caller said so), `PANEL` (a depth-thin board proud of the members),
  `FLUSH_BACK` (the end the members sit flush with), or `NONE`. Unknown is
  the normal answer.
- **depth axis**: the `Axis` a scan treats as running front to back, detected
  as the bounding-box axis with the smallest span unless given explicitly.
  Scanning divides only along the other two axes, never along the depth
  axis.
- **facing**: which end of the depth axis is the front, recorded on
  `Unit.front_at_min` (`True` at the axis's minimum end, `False` at its
  maximum, `None` when undetermined). Presentation, not structure: it
  affects which end of a division reads as left, never the tree `scan`
  builds.
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
