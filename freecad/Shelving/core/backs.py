"""Each back's placement and size from a unit's solved boards.

A back's four elevation edges sit on the board faces its
:class:`~freecad.Shelving.core.layout.BackEdge` records name, the way a Part
attachment follows its support's face, or at their recorded distance inside
the unit's outer face when a face is gone. Through the depth a back keeps its
thickness and its distance from the carcass's rear face.

All lengths are float millimeters in the unit's frame, the frame
:mod:`freecad.Shelving.core.expand` places boards in.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from freecad.Shelving.core.expand import BoardSpec
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Back, BackEdge, Face, Unit
from freecad.Shelving.core.scan import elevation_axes
from freecad.Shelving.core.solver import EPS_MM


@dataclass(frozen=True)
class BackSpec:
    """Where one back goes: its object's ``Name``, its extent and its
    minimum corner, in the unit's frame."""

    name: str
    irregular: bool
    # For an irregular back, the extent it was read with: it is moved,
    # never reshaped.
    size: Vec3
    placement: Vec3


class BackFitError(ValueError):
    """Following the boards would leave a plain back with no width or no
    height. ``name`` is the back's object ``Name``."""

    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


def _vec(axes: tuple[Axis, Axis, Axis], values_mm: tuple[float, float, float]) -> Vec3:
    """The vector holding ``values_mm[i]`` along ``axes[i]``."""
    components_mm = [0.0, 0.0, 0.0]
    for axis, value_mm in zip(axes, values_mm, strict=True):
        components_mm[axis.component_index] = value_mm
    return Vec3(components_mm[0], components_mm[1], components_mm[2])


def _edge_mm(
    edge: BackEdge,
    axis: Axis,
    at_max: bool,
    unit: Unit,
    boards: Mapping[str, BoardSpec],
) -> float:
    index = axis.component_index
    followed = None if edge.follows is None else boards.get(edge.follows.board_id)
    if edge.follows is not None and followed is not None:
        low_mm = followed.placement.component_mm(index)
        if edge.follows.face is Face.MIN:
            return low_mm
        return low_mm + followed.size.component_mm(index)
    outer_low_mm = unit.position_mm.component_mm(index)
    if at_max:
        return outer_low_mm + unit.size_mm.component_mm(index) - edge.outer_offset_mm
    return outer_low_mm + edge.outer_offset_mm


def place_backs(unit: Unit, boards: Sequence[BoardSpec]) -> list[BackSpec]:
    """One :class:`BackSpec` per back in ``unit.backs``, in that order, for
    ``unit`` solved to ``boards`` (:func:`~freecad.Shelving.core.expand.expand`).

    An edge whose followed board is not in ``boards`` keeps its outer-face
    distance. Raises :class:`BackFitError` naming the first plain back left
    no positive width or height; an irregular back keeps its size and never
    raises. Raises ``ValueError`` when ``unit`` has backs but no depth axis
    or facing, which a scan never produces.
    """
    if not unit.backs:
        return []
    if unit.depth_axis is None or unit.front_at_min is None:
        raise ValueError(f"unit {unit.id!r} has backs but no depth axis or facing")
    depth_axis = unit.depth_axis
    horizontal, vertical = elevation_axes(depth_axis)
    axes = (horizontal, vertical, depth_axis)
    by_id = {spec.node_id: spec for spec in boards}
    depth_index = depth_axis.component_index
    rear_mm = unit.position_mm.component_mm(depth_index)
    if unit.front_at_min:
        rear_mm += unit.size_mm.component_mm(depth_index)
    out: list[BackSpec] = []
    for back in unit.backs:
        h0_mm = _edge_mm(back.h_min, horizontal, False, unit, by_id)
        v0_mm = _edge_mm(back.v_min, vertical, False, unit, by_id)
        d0_mm = rear_mm + back.rear_offset_mm
        placement = _vec(axes, (h0_mm, v0_mm, d0_mm))
        if back.irregular:
            out.append(BackSpec(back.name, True, back.size_mm, placement))
            continue
        h_mm = _edge_mm(back.h_max, horizontal, True, unit, by_id) - h0_mm
        v_mm = _edge_mm(back.v_max, vertical, True, unit, by_id) - v0_mm
        if h_mm <= EPS_MM or v_mm <= EPS_MM:
            raise BackFitError(
                back.name,
                f"back {back.name!r} would be {h_mm:.1f} x {v_mm:.1f} mm",
            )
        size = _vec(axes, (h_mm, v_mm, back.size_mm.component_mm(depth_index)))
        out.append(BackSpec(back.name, False, size, placement))
    return out


def _renamed_edge(edge: BackEdge, renames: Mapping[str, str]) -> BackEdge:
    if edge.follows is None or edge.follows.board_id not in renames:
        return edge
    return replace(
        edge, follows=replace(edge.follows, board_id=renames[edge.follows.board_id])
    )


def renamed_back_boards(
    backs: Sequence[Back], renames: Mapping[str, str]
) -> tuple[Back, ...]:
    """``backs`` with every followed board id present in ``renames``
    replaced by its mapped value, the way
    :func:`freecad.Shelving.container.renamed_board_ids` renames the tree's
    boards."""
    return tuple(
        replace(
            back,
            h_min=_renamed_edge(back.h_min, renames),
            h_max=_renamed_edge(back.h_max, renames),
            v_min=_renamed_edge(back.v_min, renames),
            v_max=_renamed_edge(back.v_max, renames),
        )
        for back in backs
    )
