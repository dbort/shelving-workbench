"""Build a sample nested Carcass, solve it, and print the solved layout.

Run through the pixi environment, which puts ``shelving_core`` on the import
path:

    pixi run demo
    pixi run demo -- --svg out.svg

The sample tree is defined in code. The output is always an indented walk of the
tree, one line per node with its short id, kind, solved rectangle
``(x, z, width, height)`` in millimetres, and, for a node that sits under a
split, the ``SplitRule`` that positioned it. With ``--svg PATH``, the solved
layout is also written to ``PATH`` as an SVG elevation and a confirmation line
is printed.
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
from shelving_core.solver import Rect, SolvedLayout, solve
from shelving_core.svg import rule_label, to_svg


def _sample_carcass() -> Carcass:
    """Two split levels, a >= 3-child split, and one of each rule kind."""
    top = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(), Leaf(), Leaf()],
        rules=[Fill(), Fill(), Fill()],
        dividers=[Divider(), Divider()],
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
        default_thickness_mm=18.0,
        root=root,
    )


def _fmt_rect(rect: Rect) -> str:
    return f"({rect.x_mm:.1f},{rect.z_mm:.1f},{rect.width_mm:.1f},{rect.height_mm:.1f})"


def _print_bay(
    bay: Bay, layout: SolvedLayout, depth: int, rule: SplitRule | None
) -> None:
    indent = "  " * depth
    kind = "split" if isinstance(bay, Split) else "leaf"
    suffix = f"  rule={rule_label(rule)}" if rule is not None else ""
    print(f"{indent}{bay.id[:8]} {kind} rect={_fmt_rect(layout[bay.id])}{suffix}")
    if isinstance(bay, Split):
        for index, child in enumerate(bay.children):
            _print_bay(child, layout, depth + 1, bay.rules[index])
            if index < len(bay.dividers):
                divider = bay.dividers[index]
                print(
                    f"{indent}  {divider.id[:8]} divider "
                    f"rect={_fmt_rect(layout[divider.id])}"
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
    layout = solve(carcass)
    print(
        f"Carcass {carcass.width_mm:.0f} x {carcass.height_mm:.0f} x "
        f"{carcass.depth_mm:.0f} mm, default thickness "
        f"{carcass.default_thickness_mm:.0f} mm"
    )
    _print_bay(carcass.root, layout, 0, None)

    svg_path: pathlib.Path | None = args.svg
    if svg_path is not None:
        svg_path.write_text(to_svg(carcass, layout), encoding="utf-8")
        print(f"wrote {svg_path}")


if __name__ == "__main__":
    main()
