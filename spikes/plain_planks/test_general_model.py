"""Spike tests: the general split tree reproduces the carcass and goes past it.

The claim under test is that `Carcass` is a specialisation, not a primitive: a
closed box built from ordinary items expands to exactly what the carcass model
expands to, and the same tree also expresses a stepped outline, a plank that
runs through, and two planks face to face, none of which the shell rule can.
"""

import pytest

from shelving_core import expand as core_expand
from shelving_core import layout as core_layout
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.solver import LayoutSolveError
from spikes.plain_planks.general_model import (
    Bay,
    Divide,
    Plank,
    Sub,
    Unit,
    Void,
    bays,
    closed_box,
    expand,
    solve,
)

PLY18 = MaterialId("ply18")
MDF12 = MaterialId("mdf12")
CATALOG = Catalog(
    entries={
        PLY18: MaterialEntry(PLY18, "ply 18", 18.0, "plywood"),
        MDF12: MaterialEntry(MDF12, "mdf 12", 12.0, "mdf"),
    }
)
HORIZONTAL = core_layout.Orientation.HORIZONTAL
VERTICAL = core_layout.Orientation.VERTICAL


def _geometry(specs: list[core_expand.PlankSpec]) -> list[tuple[float, ...]]:
    """Plank sizes and placements, order-independent, for comparing two models."""
    return sorted(
        tuple(
            round(v, 6)
            for v in (
                s.size.x_mm,
                s.size.y_mm,
                s.size.z_mm,
                s.placement.x_mm,
                s.placement.y_mm,
                s.placement.z_mm,
            )
        )
        for s in specs
    )


def _shelves(count: int, material: MaterialId | None = None) -> Divide:
    """A stack of ``count`` equal bays separated by ``count - 1`` shelves."""
    items: list[Plank | Sub] = [Sub(Bay())]
    for _ in range(count - 1):
        items.append(Plank(material=material, role="shelf"))
        items.append(Sub(Bay()))
    return Divide(orientation=HORIZONTAL, items=items)


@pytest.mark.parametrize("openings", [1, 2, 4])
def test_closed_box_matches_the_carcass_model(openings: int) -> None:
    """The general tree reproduces the carcass expansion plank for plank."""
    general = closed_box(900.0, 1800.0, 300.0, PLY18, _shelves(openings))
    if openings == 1:
        root: core_layout.Bay = core_layout.Leaf()
    else:
        root = core_layout.Split(
            orientation=HORIZONTAL,
            children=[core_layout.Leaf() for _ in range(openings)],
            rules=[core_layout.Fill() for _ in range(openings)],
            dividers=[core_layout.Divider() for _ in range(openings - 1)],
        )
    carcass = core_layout.Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=root,
    )
    assert _geometry(expand(general, CATALOG)) == _geometry(
        core_expand.expand(carcass, CATALOG)
    )
    assert len(bays(general)) == openings


def test_closed_box_matches_the_carcass_model_when_nested() -> None:
    """A vertical split with a nested horizontal one, and a divider in another
    material, still matches."""
    general = closed_box(
        1200.0,
        1800.0,
        300.0,
        PLY18,
        Divide(
            orientation=VERTICAL,
            items=[
                Sub(Bay(), core_layout.Fixed(size_mm=300.0)),
                Plank(material=MDF12, role="divider"),
                Sub(_shelves(3)),
            ],
        ),
    )
    carcass = core_layout.Carcass(
        width_mm=1200.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=core_layout.Split(
            orientation=VERTICAL,
            children=[
                core_layout.Leaf(),
                core_layout.Split(
                    orientation=HORIZONTAL,
                    children=[core_layout.Leaf() for _ in range(3)],
                    rules=[core_layout.Fill() for _ in range(3)],
                    dividers=[core_layout.Divider(), core_layout.Divider()],
                ),
            ],
            rules=[core_layout.Fixed(size_mm=300.0), core_layout.Fill()],
            dividers=[core_layout.Divider(material=MDF12)],
        ),
    )
    assert _geometry(expand(general, CATALOG)) == _geometry(
        core_expand.expand(carcass, CATALOG)
    )


def _stepped_unit() -> Unit:
    """Three columns of falling height on a continuous floor: the shape the
    carcass shell rule cannot state.

    Each column is a stack of a bay, its own top, and the void above it, so the
    step is nothing but a ``Void`` taking the leftover height.
    """

    def column(void_mm: float) -> Sub:
        items: list[Plank | Sub] = [Sub(Bay()), Plank(role="top")]
        if void_mm > 0:
            items.append(Sub(Void(), core_layout.Fixed(size_mm=void_mm)))
        return Sub(Divide(orientation=HORIZONTAL, items=items))

    return Unit(
        width_mm=1200.0,
        height_mm=1200.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Divide(
            orientation=HORIZONTAL,
            items=[
                Plank(role="bottom"),
                Sub(
                    Divide(
                        orientation=VERTICAL,
                        items=[
                            Plank(role="left_side"),
                            column(0.0),
                            Plank(role="divider"),
                            column(300.0),
                            Plank(role="divider"),
                            column(600.0),
                            Plank(role="right_side"),
                        ],
                    )
                ),
            ],
        ),
    )


def test_stepped_outline_expands_with_falling_tops() -> None:
    unit = _stepped_unit()
    specs = expand(unit, CATALOG)
    tops = sorted(
        (s.placement.z_mm + s.size.z_mm, s.size.x_mm)
        for s in specs
        if s.placement.x_mm > 0 and s.size.z_mm == 18.0 and s.placement.z_mm > 18.0
    )
    # Three tops, each 300 mm lower than the last, and none spanning the unit.
    assert [round(z, 1) for z, _ in tops] == [600.0, 900.0, 1200.0]
    assert all(width < unit.width_mm for _, width in tops)
    # The floor still runs the full width and the sides are captured on it.
    floor = next(s for s in specs if s.placement.z_mm == 0.0)
    assert floor.size.x_mm == unit.width_mm
    assert len(bays(unit)) == 3, "a Void is not a bay"


def test_a_void_is_not_geometry() -> None:
    """A stepped unit emits no plank for the empty space above a short column."""
    plain = closed_box(1200.0, 1200.0, 300.0, PLY18)
    # A floor, four uprights, and one top per column: the two Voids that make
    # the steps contribute nothing.
    assert len(expand(_stepped_unit(), CATALOG)) == 8
    assert len(expand(plain, CATALOG)) == 4


def test_two_planks_face_to_face() -> None:
    """A framed wall's double top plate: two planks adjacent in one split, which
    the carcass shell rule has no way to express."""
    wall = Unit(
        width_mm=2400.0,
        height_mm=1200.0,
        depth_mm=140.0,
        default_material=PLY18,
        root=Divide(
            orientation=HORIZONTAL,
            items=[
                Plank(role="bottom"),
                Sub(Bay()),
                Plank(role="top"),
                Plank(role="top"),
            ],
        ),
    )
    specs = sorted(expand(wall, CATALOG), key=lambda s: s.placement.z_mm)
    zs = [round(s.placement.z_mm, 3) for s in specs]
    assert zs == [0.0, 1164.0, 1182.0]
    # The two plates touch: the upper starts exactly where the lower ends.
    assert zs[2] - zs[1] == 18.0


def test_a_shelf_can_run_through_the_sides() -> None:
    """Lap order is the order the splits nest, so a through-shelf is just a
    plank higher up the tree. The carcass model reserves this as an unhonoured
    per-joint override."""
    unit = Unit(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Divide(
            orientation=HORIZONTAL,
            items=[
                Plank(role="bottom"),
                Sub(
                    Divide(
                        orientation=VERTICAL,
                        items=[Plank(), Sub(Bay()), Plank()],
                    )
                ),
                Plank(role="shelf"),
                Sub(
                    Divide(
                        orientation=VERTICAL,
                        items=[Plank(), Sub(Bay()), Plank()],
                    )
                ),
                Plank(role="top"),
            ],
        ),
    )
    specs = expand(unit, CATALOG)
    through = [s for s in specs if s.size.x_mm == unit.width_mm]
    # Bottom, the mid shelf, and top all run the full width; the four sides do
    # not. A carcass can only ever produce two full-width planks.
    assert len(through) == 3
    assert len([s for s in specs if s.size.x_mm < unit.width_mm]) == 4


def test_per_plank_inset_keeps_the_rear_flush() -> None:
    """The real unit's shape: a shallower plank set back from the front with its
    rear flush, which is how a unit sits against a wall."""
    unit = closed_box(
        900.0,
        1800.0,
        300.0,
        PLY18,
        Divide(
            orientation=HORIZONTAL,
            items=[
                Sub(Bay()),
                Plank(front_inset_mm=76.2, role="shelf"),
                Sub(Bay()),
            ],
        ),
    )
    specs = expand(unit, CATALOG)
    shelf = next(s for s in specs if s.placement.y_mm > 0)
    assert round(shelf.placement.y_mm, 1) == 76.2
    assert round(shelf.size.y_mm, 1) == 223.8
    # Rear flush with the rest of the unit.
    assert round(shelf.placement.y_mm + shelf.size.y_mm, 1) == unit.depth_mm
    assert all(round(s.size.y_mm, 1) == 300.0 for s in specs if s.placement.y_mm == 0)


def test_shell_overflow_is_an_ordinary_solve_error() -> None:
    """The shell distributes with everything else, so a unit too short for its
    own top and bottom fails the same way an over-constrained split does."""
    unit = closed_box(900.0, 30.0, 300.0, PLY18)
    with pytest.raises(LayoutSolveError) as info:
        solve(unit, CATALOG)
    assert info.value.reason in ("overflow", "nonpositive_opening")
