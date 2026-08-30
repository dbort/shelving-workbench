# Shelving Workbench

A FreeCAD 1.0 workbench for parametric shelving. A unit is designed as a flat
front elevation and expands into individually editable 3D plank solids; editing
the elevation reflows the 3D. The layout math lives in a pure-Python core
(`shelving_core`) that never imports FreeCAD, so it is testable without a GUI.
See [`docs/architecture.md`](docs/architecture.md) for the design of record and
[`docs/roadmap.md`](docs/roadmap.md) for the milestone breakdown.

## Development

```sh
pip install -e .[dev]
./test.sh --fast
```

The fast tier runs `ruff check`, `ruff format --check`, `mypy` (strict, over
`shelving_core`), the vendored-core drift check, and `pytest`. It needs no
FreeCAD.

## Dependencies

`./test.sh --full` runs a headless smoke test through `freecadcmd` and requires
FreeCAD 1.0 or later on `PATH`. Install it from
<https://www.freecad.org/downloads.php>; the conda-forge `freecad` package also
provides `freecadcmd`. The full tier hard-fails (non-zero exit) when
`freecadcmd` is not found rather than skipping.
