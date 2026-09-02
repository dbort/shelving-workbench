"""Build a sample nested Carcass, solve it, and print the solved layout.

Run through the pixi environment, which puts ``shelving_core`` on the import
path:

    pixi run demo
    pixi run demo -- --svg out.svg

The sample tree is defined in code. The output leads with the in-code material
catalog (one row per entry), then an indented walk of the tree: one line per
node with its short id, kind, solved rectangle ``(x, z, width, height)`` in
millimetres, and, for a node under a split, the ``SplitRule`` that positioned
it; divider lines also carry the resolved material name and thickness. With
``--svg PATH``, the solved layout is also written to ``PATH`` as an SVG
elevation and a confirmation line is printed.
"""

import argparse
import pathlib

from shelving_core.layout import (
    Bay,
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    SplitRule,
    Weighted,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.solver import Rect, SolvedLayout, solve
from shelving_core.svg import rule_label, to_svg

PLY18 = MaterialId("ply18")
MDF12 = MaterialId("mdf12")


def _sample_catalog() -> Catalog:
    """A default 18 mm plywood plus a 12 mm MDF for the divider override."""
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


def _sample_carcass() -> Carcass:
    """Two split levels, a >= 3-child split, and one of each rule kind."""
    top = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(), Leaf(), Leaf()],
        rules=[Fill(), Fill(), Fill()],
        dividers=[Divider(material=MDF12), Divider()],
    )
    bottom = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(), Leaf()],
        rules=[Fixed(300.0), Weighted(2.0)],
        dividers=[Divider()],
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[top, bottom],
        rules=[Weighted(1.0), Fixed(500.0)],
        dividers=[Divider()],
    )
    return Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=root,
    )


def _fmt_rect(rect: Rect) -> str:
    return f"({rect.x_mm:.1f},{rect.z_mm:.1f},{rect.width_mm:.1f},{rect.height_mm:.1f})"


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


def _print_bay(
    bay: Bay,
    layout: SolvedLayout,
    depth: int,
    rule: SplitRule | None,
    catalog: Catalog,
    default_material: MaterialId,
) -> None:
    indent = "  " * depth
    kind = "split" if isinstance(bay, Split) else "leaf"
    suffix = f"  rule={rule_label(rule)}" if rule is not None else ""
    print(f"{indent}{bay.id[:8]} {kind} rect={_fmt_rect(layout[bay.id])}{suffix}")
    if isinstance(bay, Split):
        for index, child in enumerate(bay.children):
            _print_bay(
                child, layout, depth + 1, bay.rules[index], catalog, default_material
            )
            if index < len(bay.dividers):
                divider = bay.dividers[index]
                material_id = (
                    divider.material
                    if divider.material is not None
                    else default_material
                )
                entry = catalog[material_id]
                print(
                    f"{indent}  {divider.id[:8]} divider "
                    f"rect={_fmt_rect(layout[divider.id])} "
                    f'material="{entry.name}" {entry.thickness_mm:g}mm'
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--svg",
        type=pathlib.Path,
        default=None,
        help="also write the solved layout to this path as an SVG elevation",
    )
    args = parser.parse_args()

    carcass = _sample_carcass()
    catalog = _sample_catalog()
    layout = solve(carcass, catalog)
    default_entry = catalog[carcass.default_material]
    print(
        f"Carcass {carcass.width_mm:.0f} x {carcass.height_mm:.0f} x "
        f"{carcass.depth_mm:.0f} mm, default material "
        f"{default_entry.name} ({default_entry.thickness_mm:g} mm)"
    )
    _print_catalog(catalog)
    _print_bay(carcass.root, layout, 0, None, catalog, carcass.default_material)

    svg_path: pathlib.Path | None = args.svg
    if svg_path is not None:
        svg_path.write_text(to_svg(carcass, layout, catalog), encoding="utf-8")
        print(f"wrote {svg_path}")


if __name__ == "__main__":
    main()
