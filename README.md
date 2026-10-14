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
is for and how it is built, and [`docs/roadmap.md`](docs/roadmap.md) for what
is left to do.

## Setup

```sh
tools/install-deps.sh
```

The script is idempotent. It provisions the pixi environment, pinned by
`pixi.lock`: the dev toolchain plus FreeCAD 1.1, with the project installed
editable. If `pixi` is not on `PATH`, it installs a checksum-verified
release into `~/.local/bin` and adds that directory to `~/.bashrc` and
`~/.profile`; open a new shell afterward. To install
[pixi](https://pixi.sh) yourself instead, run `pixi install` in the
checkout.

To load the workbench from this checkout in the FreeCAD GUI, see
[`docs/manual-qa.md`](docs/manual-qa.md).

## Tests

`pixi run tests` is the pre-merge gate and what CI runs. In one pass it
covers ruff, pyrefly at its strict preset, the core unit suite, the
`pixi.lock` path guard, the workflow-hardening lint, a `freecadcmd` import
check, and the headless (`tests/freecad/`), offscreen-GUI
(`tests/freecad_gui/`) and 3D-view (`tests/freecad_view/`) FreeCAD suites.
`pixi run tests -- --offline` skips the checks that need the network.

The FreeCAD suites use throwaway FreeCAD settings, never yours. Each needs
a pytest run of its own, such as `pixi run pytest tests/freecad_gui -k
drag`; any other run skips them and says so. The 3D-view suite runs on a
private virtual display: `pixi run python -m tools.xvfb_run pytest
tests/freecad_view`.

## Glossary

The vocabulary the documentation and the code share.

- **Unit**: one shelving unit, held in a container you choose. There is no
  distinguished shell: the outermost boards are the shell.
- **Region**: a bay, a void, or a division.
- **Bay**: an open compartment that is part of the unit.
- **Void**: space inside the unit's bounding box that is not part of the
  unit, such as the space above a short column. Voids make an outline
  stepped.
- **Division**: a region cut along one axis into an ordered run of boards
  and sub-regions. Two adjacent boards in a run are two boards face to
  face.
- **Board**: one physical member, a `Part::Box`; user-facing text calls it
  a panel. Its role (shelf, side, top) is a free label, since a stepped unit
  can have several tops.
- **Insets**: how far a board is set back from its region on each face
  other than the two along its own run.
- **Size rule**: how a division sizes one region: **fixed** at an exact
  size, or a **weighted** share of what is left (**fill** is an equal
  share).
- **Measurement basis**: what a fixed size measures. **Clear opening** is
  the region alone; **Spacing** runs through the next board, as a shelf
  spacing is quoted top face to top face. Switching basis moves nothing.
  When stock thickness changes, a spacing holds the next board in place and
  a clear opening moves it.
- **The drag rule**: dragging a board resizes the region before it and
  changes only that region's number, never its basis. A region that was
  sharing leftover space becomes a clear opening.
- **Local frame**: origin at the unit's front-bottom-left corner, +X right,
  +Y back, +Z up, in millimeters. A container's own placement is excluded,
  so a unit reads the same wherever it sits.
- **Depth axis**: the axis a scan treats as front to back, by default the
  shallowest. Scanning never divides along it.
- **Facing**: which end of the depth axis is the front. Often unknown, in
  which case left and right are arbitrary but the layout is still correct.
- **The cut rule**: a scan divides a region along any line no board
  crosses, so two boards meeting face to face cut as cleanly as one.
- **Snap tolerance**: edges within this distance (default 0.5 mm) count as
  one line, absorbing the small disagreements real geometry has at a joint.
- **Joint clearance**: a board end may stop up to this far (default 3 mm)
  short of the edge it spans to without creating a compartment.
- **Pinned part**: a part that is not a simple box, read by its bounding
  box. Its size drives the layout around it and it is never rewritten.
- **Stock**: a board's thickness, material, appearance, and grain. Kept
  where the Woodworking workbench keeps them, and never changed on an
  existing board.
- **Carcass board**: a board with no bay between one of its faces and the
  unit's edge along its run. A floor raised over a plinth gap is carcass.
- **Source board**: the existing board a new board copies its stock from,
  chosen among boards lying the same way: an interior board in its own run,
  then the nearest interior board, then the nearest carcass board. Failing
  those, the nearest board of any kind.
