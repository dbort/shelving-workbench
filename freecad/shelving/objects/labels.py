"""Generated `Label` text for a plank, from its role and per-role ordinal.

Import-light on purpose: nothing from `FreeCAD` / `Part`, so the functional
smoke exercises it with no running FreeCAD document.
"""

from typing import assert_never

from freecad.shelving.vendor.shelving_core.expand import PlankRole


def generated_label(role: PlankRole, ordinal_for_role: int) -> str:
    """The plank's display `Label`.

    Shell roles (`BOTTOM`, `TOP`, `LEFT_SIDE`, `RIGHT_SIDE`) map to a fixed
    string and ignore `ordinal_for_role`; `SHELF` and `DIVIDER` append it
    (`"Shelf 2"`, `"Divider 3"`).
    """
    match role:
        case PlankRole.BOTTOM:
            return "Bottom"
        case PlankRole.TOP:
            return "Top"
        case PlankRole.LEFT_SIDE:
            return "Left Side"
        case PlankRole.RIGHT_SIDE:
            return "Right Side"
        case PlankRole.SHELF:
            return f"Shelf {ordinal_for_role}"
        case PlankRole.DIVIDER:
            return f"Divider {ordinal_for_role}"
    # No `case _`: a newly added PlankRole member becomes a type error here
    # rather than a silently wrong label.
    assert_never(role)
