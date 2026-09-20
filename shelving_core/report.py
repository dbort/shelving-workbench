"""Render a :class:`~shelving_core.scan.ScanResult` as plain text.

:func:`report` is a pure function: a plane line naming the depth axis and
overall size, a facing line saying which evidence settled which end faces the
viewer (or that nothing did, and left/right below are a coin flip), the
region tree indented one level per nesting with a size on every region and
board and insets on every board, and a skipped block listing each part the
scan could not read and why. No FreeCAD import, so the fast suite exercises
it directly.
"""

from .layout import Basis, Bay, Board, Division, Fixed, Item, Void, Weighted
from .scan import FacingEvidence, ScanResult

_FACING_WHY = {
    FacingEvidence.GIVEN: "given",
    FacingEvidence.PANEL: "a back or front panel says so",
    FacingEvidence.FLUSH_BACK: "the members sit flush at one end and inset at "
    "the other, and the flush end is the rear",
}

_INDENT = "  "


def report(result: ScanResult) -> str:
    """``result`` rendered as a multi-line report: plane, facing, region
    tree, then the skipped block when ``result.skipped`` is non-empty."""
    lines = [_plane_line(result), _facing_line(result), ""]
    lines.extend(_render(result.unit.root, ""))
    if result.skipped:
        lines.append("")
        lines.append(f"skipped ({len(result.skipped)}):")
        for part in result.skipped:
            name = part.label or part.name
            lines.append(f"{_INDENT}{name} [{part.type}]: {part.reason}")
    return "\n".join(lines)


def _plane_line(result: ScanResult) -> str:
    unit = result.unit
    size = unit.size_mm
    depth = unit.depth_axis.value if unit.depth_axis is not None else "?"
    return f"depth axis {depth}, size {size.x_mm:g} x {size.y_mm:g} x {size.z_mm:g} mm"


def _facing_line(result: ScanResult) -> str:
    front_at_min = result.unit.front_at_min
    if front_at_min is None:
        return (
            "WARNING: nothing says which side this unit faces, so left and "
            "right below are a coin flip: the tree is correct either way."
        )
    end = "minimum" if front_at_min else "maximum"
    # scan() only ever pairs NONE with front_at_min is None, but report() is
    # public over any ScanResult, so an unrecognised pairing gets a neutral
    # fallback rather than a KeyError.
    why = _FACING_WHY.get(result.facing_evidence, "unspecified evidence")
    return f"front at the {end} end of the depth axis ({why})"


def _rule_suffix(item: Bay | Void | Division) -> str:
    rule = item.rule
    if isinstance(rule, Fixed):
        basis = "with next" if rule.basis is Basis.WITH_NEXT else "clear"
        return f", {rule.size_mm:g} mm ({basis})"
    if isinstance(rule, Weighted):
        return f", weight {rule.weight:g}"
    return ""


def _insets_suffix(board: Board) -> str:
    insets = board.insets
    parts = []
    for axis, lo_mm, hi_mm in (
        ("x", insets.x_min_mm, insets.x_max_mm),
        ("y", insets.y_min_mm, insets.y_max_mm),
        ("z", insets.z_min_mm, insets.z_max_mm),
    ):
        if lo_mm or hi_mm:
            parts.append(f"{axis} {lo_mm:g}/{hi_mm:g}")
    if not parts:
        return ""
    return ", insets " + ", ".join(parts)


def _render(item: Item, indent: str) -> list[str]:
    if isinstance(item, Board):
        material = item.material or "default material"
        role = item.role or item.id
        return [f"{indent}board {role} ({material}){_insets_suffix(item)}"]
    if isinstance(item, Bay):
        return [f"{indent}bay{_rule_suffix(item)}"]
    if isinstance(item, Void):
        return [f"{indent}void{_rule_suffix(item)}"]
    lines = [f"{indent}division along {item.axis.value}{_rule_suffix(item)}"]
    for child in item.items:
        lines.extend(_render(child, indent + _INDENT))
    return lines
