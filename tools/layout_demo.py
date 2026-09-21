"""Build a sample stepped ``Unit``, solve it, expand it, and print the result.

Run through the pixi environment, or directly with ``python3``; either way
``freecad.Shelving.core`` resolves from the checkout via the project's
editable install (`pixi.toml`'s `[pypi-dependencies]`), which puts the repo
root on `sys.path` before this script's own imports run:

    pixi run demo
    pixi run demo -- --svg out.svg

The sample tree and catalog are defined in code. Output, in order:

- the material catalog: one row per entry;
- an indented walk of the region tree: per region, its short id, kind, solved
  ``Space``, and the ``SizeRule`` that positioned it (every region but the
  root, which has no parent to size it);
- the expanded board table: one row per physical board (role, size,
  minimum-corner placement, material name), then a total-board-volume line.

``--svg PATH`` also writes the solved layout to ``PATH`` as an SVG elevation.
"""

import argparse
import os
import pathlib
import sys

# Defensive against someone running this script outside `pixi run`/`pixi
# shell` (e.g. a bare venv with the editable install skipped): the editable
# install's `.pth` file is what resolves `freecad.Shelving.core` in the
# normal case (verified directly), so this insert is redundant coverage,
# not the primary mechanism.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# `freecad/Shelving/` living under a `freecad` namespace-package portion
# means importing anything under it resolves the installed FreeCAD
# distribution's own `freecad/__init__.py` first (a regular package always
# wins over a namespace-portion directory of the same name). That file
# falls back to guessing its own lib directory and prints a diagnostic line
# to stdout whenever `PATH_TO_FREECAD_LIBDIR` is unset. Verified directly:
# without this, `pixi run demo`'s first line of output was that diagnostic,
# not the catalog header below. Setting it to this interpreter's own lib
# directory (what the fallback guesses anyway, for the pixi-provided
# interpreter) makes the import resolve the same FreeCAD build silently.
os.environ.setdefault("PATH_TO_FREECAD_LIBDIR", os.path.join(sys.prefix, "lib"))

from freecad.Shelving.core.expand import (  # noqa: E402
    BoardSpec,
    expand,
    total_volume_mm3,
)
from freecad.Shelving.core.geometry import Space, Vec3  # noqa: E402
from freecad.Shelving.core.layout import (  # noqa: E402
    Axis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Region,
    SizeRule,
    Unit,
    Void,
)
from freecad.Shelving.core.materials import (  # noqa: E402
    Catalog,
    MaterialEntry,
    MaterialId,
)
from freecad.Shelving.core.solver import solve  # noqa: E402
from freecad.Shelving.core.svg import to_svg  # noqa: E402

PLY18 = MaterialId("ply18")
MDF12 = MaterialId("mdf12")


def _sample_catalog() -> Catalog:
    """A default 18 mm plywood plus a 12 mm MDF for the shelf override."""
    return Catalog(
        entries={
            PLY18: MaterialEntry(
                id=PLY18,
                name="18 mm birch ply",
                thickness_mm=18.0,
                material_type="plywood",
                nominal_thickness='3/4"',
            ),
            MDF12: MaterialEntry(
                id=MDF12,
                name="12 mm MDF",
                thickness_mm=12.0,
                material_type="mdf",
            ),
        }
    )


def _column(void_mm: float, prefix: str, *, with_shelf: bool = False) -> Division:
    """A stack of a bay, its own top, and (if positive) the void above it.

    The step in the outline is the ``Void`` taking the leftover height above
    a shorter column; ``with_shelf`` splits the bay in two around a divider
    board in a second material.
    """
    body: Item = (
        Division(
            axis=Axis.Z,
            items=[
                Bay(id=f"{prefix}_lower_bay"),
                Board(material=MDF12, role="shelf", id=f"{prefix}_shelf"),
                Bay(id=f"{prefix}_upper_bay"),
            ],
            id=f"{prefix}_body",
        )
        if with_shelf
        else Bay(id=f"{prefix}_bay")
    )
    items: list[Item] = [body, Board(role="top", id=f"{prefix}_top")]
    if void_mm > 0:
        items.append(Void(rule=Fixed(void_mm), id=f"{prefix}_void"))
    return Division(axis=Axis.Z, items=items, id=f"{prefix}_column")


def _sample_unit() -> Unit:
    """Three columns of falling height on a continuous floor: a stepped
    outline the carcass shell rule could never state."""
    return Unit(
        size_mm=Vec3(1200.0, 300.0, 1200.0),
        default_material=PLY18,
        depth_axis=Axis.Y,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom", id="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(role="left_side", id="left_side"),
                        _column(0.0, "col0", with_shelf=True),
                        Board(role="divider", id="divider0"),
                        _column(300.0, "col1"),
                        Board(role="divider", id="divider1"),
                        _column(600.0, "col2"),
                        Board(role="right_side", id="right_side"),
                    ],
                    id="middle",
                ),
            ],
            id="root",
        ),
    )


def _fmt_space(space: Space) -> str:
    o, s = space.origin, space.size
    return (
        f"origin=({o.x_mm:.1f},{o.y_mm:.1f},{o.z_mm:.1f}) "
        f"size=({s.x_mm:.1f},{s.y_mm:.1f},{s.z_mm:.1f})"
    )


def _rule_label(rule: SizeRule) -> str:
    """Human-readable one-liner for the rule that positioned a region."""
    match rule:
        case Fixed():
            return f"Fixed {rule.size_mm:g} mm ({rule.basis.value})"
        case Fill():
            return "Fill"
        case _:
            return f"Weighted {rule.weight:g}"


def _print_catalog(catalog: Catalog) -> None:
    print("Catalog:")
    for entry in catalog:
        row = (
            f"  {entry.id}  {entry.name}  {entry.thickness_mm:g}mm  "
            f"{entry.material_type}"
        )
        if entry.nominal_thickness is not None:
            row += f"  (nominal {entry.nominal_thickness})"
        print(row)


def _kind(region: Region) -> str:
    if isinstance(region, Division):
        return "division"
    if isinstance(region, Void):
        return "void"
    return "bay"


def _print_region(
    region: Region, spaces: dict[str, Space], depth: int, rule: SizeRule | None
) -> None:
    indent = "  " * depth
    suffix = f"  rule={_rule_label(rule)}" if rule is not None else ""
    print(
        f"{indent}{region.id[:12]} {_kind(region)} "
        f"{_fmt_space(spaces[region.id])}{suffix}"
    )
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                continue
            _print_region(item, spaces, depth + 1, item.rule)


def _print_boards(specs: list[BoardSpec], catalog: Catalog) -> None:
    print("Boards:")
    for spec in specs:
        size = f"{spec.size.x_mm:g} x {spec.size.y_mm:g} x {spec.size.z_mm:g} mm"
        placement = (
            f"({spec.placement.x_mm:g}, {spec.placement.y_mm:g}, "
            f"{spec.placement.z_mm:g})"
        )
        name = catalog[spec.material].name
        print(f"  {spec.role:<11} {size}  at {placement}  {name}")
    print(f"Total board volume: {total_volume_mm3(specs):.0f} mm^3")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--svg",
        type=pathlib.Path,
        default=None,
        help="also write the solved layout to this path as an SVG elevation",
    )
    args = parser.parse_args()

    unit = _sample_unit()
    catalog = _sample_catalog()
    spaces = solve(unit, catalog)
    default_entry = catalog[unit.default_material]
    print(
        f"Unit {unit.size_mm.x_mm:.0f} x {unit.size_mm.y_mm:.0f} x "
        f"{unit.size_mm.z_mm:.0f} mm, default material "
        f"{default_entry.name} ({default_entry.thickness_mm:g} mm)"
    )
    _print_catalog(catalog)
    _print_region(unit.root, spaces, 0, None)
    _print_boards(expand(unit, catalog), catalog)

    svg_path: pathlib.Path | None = args.svg
    if svg_path is not None:
        svg_path.write_text(to_svg(unit, spaces, catalog), encoding="utf-8")
        print(f"wrote {svg_path}")


if __name__ == "__main__":
    main()
