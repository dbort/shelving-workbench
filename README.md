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
inside `pixi shell`.
