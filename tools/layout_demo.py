"""Build a sample nested Carcass, solve it, and print the solved layout.

Run from the repo root:

    python tools/layout_demo.py     (or: pixi run demo)

There is no command line: the sample tree is defined in code. The output is an
indented walk of the tree, one line per node with its short id, kind, solved
rectangle ``(x, z, width, height)`` in millimetres, and, for a node that sits
under a split, the ``SplitRule`` that positioned it.

The repo root is put on ``sys.path`` so the script runs the same whether or not
``shelving_core`` is installed into the active environment (the pixi env, for
one, imports it straight from the checkout).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shelving_core.layout import (  # noqa: E402
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
from shelving_core.solver import Rect, SolvedLayout, solve  # noqa: E402


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


def _rule_label(rule: SplitRule) -> str:
    match rule:
        case Fixed(size_mm=size_mm):
            return f"fixed {size_mm:.1f}mm"
        case Weighted(weight=weight):
            return f"weighted {weight:g}"
        case Fill():
            return "fill"


def _print_bay(
    bay: Bay, layout: SolvedLayout, depth: int, rule: SplitRule | None
) -> None:
    indent = "  " * depth
    kind = "split" if isinstance(bay, Split) else "leaf"
    suffix = f"  rule={_rule_label(rule)}" if rule is not None else ""
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
    carcass = _sample_carcass()
    layout = solve(carcass)
    print(
        f"Carcass {carcass.width_mm:.0f} x {carcass.height_mm:.0f} x "
        f"{carcass.depth_mm:.0f} mm, default thickness "
        f"{carcass.default_thickness_mm:.0f} mm"
    )
    _print_bay(carcass.root, layout, 0, None)


if __name__ == "__main__":
    main()
