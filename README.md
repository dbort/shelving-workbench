# Shelving Workbench

A FreeCAD 1.0 workbench for parametric shelving. A unit is designed as a flat
front elevation and expands into individually editable 3D plank solids; editing
the elevation reflows the 3D. The layout math lives in a pure-Python core
(`shelving_core`) that never imports FreeCAD, so it is testable without a GUI.
See [`docs/architecture.md`](docs/architecture.md) for the design of record and
[`docs/roadmap.md`](docs/roadmap.md) for the milestone breakdown.

To eyeball a solved layout, run `pixi run demo`: it builds a sample nested
carcass, runs the spacing solver, and prints the resulting rectangle for every
bay and divider. Add `pixi run demo -- --svg layout.svg` to also write the
solved layout as an SVG elevation, which opens with Quick Look (spacebar in
Finder) or any browser.

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
- a headless FreeCAD import smoke through `freecadcmd`.

It runs inside the pixi environment, which supplies every tool including
FreeCAD. To run only the workflow lint, use `bash tools/lint-workflows.sh` from
inside `pixi shell`. For offline work, `pixi run tests -- --offline` skips the
checks that need network access.

## Glossary

The layout vocabulary and how each term maps onto the code in `shelving_core`.

- **Carcass**: the shelving box. `Carcass` in `shelving_core.layout` holds the
  outer `width_mm`, `height_mm`, and `depth_mm`, a `default_material`, a root
  `Bay`, and a persistent `id`.
- **Bay**: a rectangular region of the elevation. `Bay = Leaf | Split`: it is
  either open or subdivided.
- **Leaf**: an open compartment, a `Bay` with no further subdivision. `Leaf`
  carries only its `id`.
- **Split**: a `Bay` divided along one axis into two or more child bays.
  `Split` holds an `Orientation` (`HORIZONTAL` or `VERTICAL`), the ordered
  `children`, one `SplitRule` per child (`Fixed`, `Weighted`, or `Fill`), and
  one `Divider` per gap between consecutive children.
- **Divider**: the panel in the gap between two consecutive split children.
  `Divider` in `shelving_core.layout` carries an optional `material` override
  and a reserved `lap`. A divider in a `HORIZONTAL` split is a shelf
  (`PlankRole.SHELF`); a divider in a `VERTICAL` split is a vertical divider
  (`PlankRole.DIVIDER`).
- **Plank**: one physical panel of the finished unit. `expand` emits one
  `PlankSpec` per plank; the FreeCAD layer turns each into a solid.
- **Joint**: where the edge of one plank meets another plank. v1 has no joint
  data type; the carcass rule alone decides how planks meet.
- **Butt joint**: the only construction in v1. One plank's square end meets the
  face of another; there is no dado, rabbet, or groove.
- **Lap order**: at a joint, which plank runs **continuous** (its length passes
  straight through the joint) and which is **captured** (its length stops
  against the neighbour's face). `LapOrder` in `shelving_core.layout` has the
  members `THROUGH` and `CAPTURED`; `Divider.lap` is a reserved per-joint
  override that no layout or expansion code reads in M2.
- **Default carcass rule**: the top and bottom run continuous the full width
  and depth; the two sides and every divider are captured. `expand` always
  applies this rule.
- **Catalog**: the material table. `Catalog` in `shelving_core.materials` maps
  a `MaterialId` to a `MaterialEntry`.
- **Material entry**: one stock record. `MaterialEntry` carries `id`, `name`,
  `thickness_mm`, `material_type`, and an optional `nominal_thickness` label.
  The solver resolves a `MaterialId` to `thickness_mm`.
- **MaterialId**: a `NewType('MaterialId', str)`. `Carcass.default_material`
  applies to the shell and to any `Divider` that sets no `material` of its own.
- **PlankSpec**: the output record of `expand`, a frozen dataclass
  `(node_id, role, size, placement, material)`. `node_id` is the owning
  `Divider.id` for a divider plank and the literal `f"{carcass.id}:{role.value}"`
  for a shell plank. `size` and `placement` are `Vec3`. There is no grain
  field yet.
- **PlankRole**: a `StrEnum` naming what a plank is: `LEFT_SIDE`, `RIGHT_SIDE`,
  `TOP`, `BOTTOM`, `SHELF`, `DIVIDER`.
- **Local coordinate frame**: origin at the carcass front-bottom-left corner,
  `+X` right (width), `+Y` back (depth), `+Z` up (height). A
  `PlankSpec.placement` is the plank's minimum corner in that frame; `size` is
  its extent along each axis. All lengths are float millimetres.
- **Vec3**: a frozen dataclass `(x_mm, y_mm, z_mm)` in `shelving_core.expand`,
  used for both a plank's `size` and its `placement`.
- **Spacing solver**: `solve(carcass, catalog)` in `shelving_core.solver`. It
  insets the carcass by the default panel thickness, then places one `Rect`
  per `Leaf`, `Split`, and `Divider` id, distributing slack along each split's
  axis by its `SplitRule`s.
- **expand**: `expand(carcass, catalog)` in `shelving_core.expand`. It calls
  `solve`, then returns the `list[PlankSpec]` for the shell and every divider.
  Like the solver, it has no FreeCAD dependency and produces plain data.
