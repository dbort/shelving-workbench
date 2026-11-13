"""Tests for the stored rule record."""

import dataclasses
import json
from collections.abc import Mapping

import pytest

from freecad.Shelving.core.edit import unlock
from freecad.Shelving.core.expand import expand
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    Division,
    Equal,
    EvenSpacing,
    Item,
    Region,
    RunEnd,
    Unit,
    Void,
    constraint_regions,
)
from freecad.Shelving.core.record import (
    RULE_RECORD_VERSION,
    OpenReport,
    StoredRules,
    parse_rules,
    region_keys,
    restore_rules,
    rule_key,
    rules_from_json,
    rules_to_json,
    with_stored_rules,
)
from freecad.Shelving.core.scan import DEFAULT_CLEARANCE_MM, Box, scan
from freecad.Shelving.core.solver import solve

# --- rule_key() -------------------------------------------------------------


def test_rule_key_same_pair_gives_the_same_key() -> None:
    assert rule_key("a", "b") == rule_key("a", "b")
    assert rule_key(None, None) == rule_key(None, None)


def test_rule_key_distinct_pairs_give_distinct_keys() -> None:
    assert rule_key("a", "b") != rule_key("a", "c")
    assert rule_key("a", "b") != rule_key("c", "b")
    assert rule_key("a", "b") != rule_key("b", "a")
    assert rule_key(None, "b") != rule_key("a", "b")
    assert rule_key("a", None) != rule_key("a", "b")
    assert rule_key(None, "b") != rule_key("b", None)


# --- the units the tests store and rescan ------------------------------------


def _b(role: str) -> Board:
    """A board whose id matches its role, standing in for what sh-018 makes
    true in the real pipeline: a board's id is its stable FreeCAD object
    name, which is also what a scanned board's role is read from."""
    return Board(thickness_mm=18.0, role=role, id=role)


def _closed_box_unit(
    bay2_lock: Basis | None = None, *, mid_lock: Basis | None = None
) -> Unit:
    """Four 427.5 mm bays behind three shelves in a closed box, every region
    unlocked unless told otherwise."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        root=Division(
            axis=Axis.Z,
            items=[
                _b("bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        _b("left"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(size_mm=427.5, id="bay1"),
                                _b("shelf1"),
                                Bay(size_mm=427.5, lock=bay2_lock, id="bay2"),
                                _b("shelf2"),
                                Bay(size_mm=427.5, id="bay3"),
                                _b("shelf3"),
                                Bay(size_mm=427.5, id="bay4"),
                            ],
                            size_mm=864.0,
                        ),
                        _b("right"),
                    ],
                    size_mm=1764.0,
                    lock=mid_lock,
                ),
                _b("top"),
            ],
        ),
    )


def _with_next_unit() -> Unit:
    """A closed box whose interior shelf spacing is quoted top face to top
    face: "spaced_bay" covers itself plus "shelf", 400 mm in all. A clear
    opening and a spacing place their boards identically, so a scan alone
    always locks in ``Basis.CLEAR``."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 1200.0),
        root=Division(
            axis=Axis.Z,
            items=[
                _b("bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        _b("left"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(size_mm=382.0, lock=Basis.WITH_NEXT, id="spaced"),
                                _b("shelf"),
                                Bay(size_mm=764.0, id="top_bay"),
                            ],
                            size_mm=564.0,
                        ),
                        _b("right"),
                    ],
                    size_mm=1164.0,
                ),
                _b("top"),
            ],
        ),
    )


def _stabilize_board_ids(region: Region) -> Region:
    """``region`` with every ``Board``'s ``id`` replaced by its ``role``.

    A scanned board's ``id`` is its box's name, which ``expand`` gives the
    original board's id; this makes the stand-in explicit, as sh-018's real
    pipeline makes a board's id its stable FreeCAD object name.
    """
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(dataclasses.replace(item, id=item.role))
        else:
            new_items.append(_stabilize_board_ids(item))
    return dataclasses.replace(region, items=new_items)


def _rescan_with_board_moved(
    unit: Unit, board_id: str = "", up_mm: float = 0.0
) -> Unit:
    """``unit`` taken to boards and back through ``scan``, after ``board_id``
    was moved ``up_mm`` by hand."""
    boxes: list[Box] = []
    for spec in expand(unit):
        corner = spec.placement
        if spec.node_id == board_id:
            corner = Vec3(corner.x_mm, corner.y_mm, corner.z_mm + up_mm)
        boxes.append(Box(name=spec.node_id, corner_mm=corner, size_mm=spec.size))
    rescanned = scan(boxes).unit
    return dataclasses.replace(rescanned, root=_stabilize_board_ids(rescanned.root))


def _restored(original: Unit, rescanned: Unit) -> Unit:
    return with_stored_rules(rescanned, parse_rules(rules_to_json(original)))


def _locks(unit: Unit) -> Mapping[str, Basis | None]:
    """Each non-root region's lock, by its record key."""
    keys = region_keys(unit)
    found: dict[str, Basis | None] = {}

    def walk(region: Region) -> None:
        if isinstance(region, Division):
            for item in region.items:
                if not isinstance(item, Board):
                    found[item.id] = item.lock
                    walk(item)

    walk(unit.root)
    return {key: found[region_id] for key, region_id in keys.items()}


def _board_ids(region: Region) -> list[str]:
    if not isinstance(region, Division):
        return []
    ids: list[str] = []
    for item in region.items:
        ids += [item.id] if isinstance(item, Board) else _board_ids(item)
    return ids


def _assert_same_spaces(a: Unit, b: Unit) -> None:
    """Every board of ``a`` and ``b`` in the same place; region ids differ
    across a rescan, board ids do not."""
    spaces_a, spaces_b = solve(a), solve(b)
    for board_id in _board_ids(a.root):
        assert spaces_a[board_id] == spaces_b[board_id], board_id


# --- rules_to_json() ---------------------------------------------------------


def test_rules_to_json_emits_one_entry_per_locked_region_and_nothing_else() -> None:
    unit = _closed_box_unit(Basis.CLEAR, mid_lock=Basis.WITH_NEXT)
    assert json.loads(rules_to_json(unit)) == {
        "schema_version": RULE_RECORD_VERSION,
        "locks": {
            rule_key("bottom", "top"): {"basis": "with_next"},
            rule_key("shelf1", "shelf2"): {"basis": "clear"},
        },
        "constraints": [],
    }
    assert RULE_RECORD_VERSION == 2


def test_rules_to_json_of_an_unlocked_unit_has_no_locks() -> None:
    doc = json.loads(rules_to_json(_closed_box_unit()))
    assert doc == {"schema_version": 2, "locks": {}, "constraints": []}


# --- rules_from_json() --------------------------------------------------------


def test_rules_from_json_round_trips_both_bases() -> None:
    unit = _closed_box_unit(Basis.CLEAR, mid_lock=Basis.WITH_NEXT)
    assert rules_from_json(rules_to_json(unit)).locks == {
        rule_key("bottom", "top"): Basis.WITH_NEXT,
        rule_key("shelf1", "shelf2"): Basis.CLEAR,
    }


@pytest.mark.parametrize(
    "text",
    [
        # The per-region size rules an older workbench stored here.
        json.dumps(
            {
                "schema_version": 1,
                "rules": {
                    "a|b": {"type": "fixed", "size_mm": 300.0, "basis": "clear"},
                    "b|c": {"type": "weighted", "weight": 2.0},
                    "c|d": {"type": "fill"},
                },
            }
        ),
        json.dumps({"schema_version": 2, "locks": {}}),
        # A version 1 record of locks alone, the shape sh-046 wrote.
        json.dumps({"schema_version": 1, "locks": {"a|b": {"basis": "clear"}}}),
        json.dumps({"schema_version": 1, "locks": {}, "constraints": []}),
        json.dumps({"schema_version": 2, "locks": {}, "constraints": {}}),
        json.dumps(
            {"schema_version": 2, "locks": {}, "constraints": [{"kind": "equal"}]}
        ),
        json.dumps(
            {
                "schema_version": 2,
                "locks": {},
                "constraints": [
                    {
                        "kind": "equal",
                        "basis": "clear",
                        "active": 1,
                        "openings": ["a|b", "c|d"],
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 2,
                "locks": {},
                "constraints": [
                    {
                        "kind": "equal",
                        "basis": "clear",
                        "active": True,
                        "openings": ["a|b"],
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 2,
                "locks": {},
                "constraints": [
                    {
                        "kind": "even_spacing",
                        "basis": "clear",
                        "active": True,
                        "run": "~root",
                        "start": "",
                        "end": "~end",
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 2,
                "locks": {},
                "constraints": [
                    {
                        "kind": "aligned",
                        "basis": "clear",
                        "active": True,
                    }
                ],
            }
        ),
        json.dumps({"schema_version": True, "locks": {}}),
        json.dumps({"locks": {"a|b": {"basis": "clear"}}}),
        json.dumps({"schema_version": 1, "locks": {}, "rules": {}}),
        json.dumps({"schema_version": 1, "locks": []}),
        json.dumps({"schema_version": 1, "locks": {"a|b": {"basis": "spacing"}}}),
        json.dumps({"schema_version": 1, "locks": {"a|b": "clear"}}),
        json.dumps(
            {"schema_version": 1, "locks": {"a|b": {"basis": "clear", "size_mm": 3}}}
        ),
        json.dumps([1, 2]),
        "not json at all",
        "",
    ],
)
def test_rules_from_json_reads_any_other_shape_as_no_locks(text: str) -> None:
    assert rules_from_json(text) == StoredRules()
    assert parse_rules(text) is None


def test_parse_locks_tells_an_empty_record_from_no_record() -> None:
    assert parse_rules(rules_to_json(_closed_box_unit())) == StoredRules()


# --- with_stored_rules() ------------------------------------------------------


def test_with_stored_rules_locks_a_matching_region_and_moves_nothing() -> None:
    scanned = _closed_box_unit()
    restored = with_stored_rules(
        scanned, StoredRules({rule_key("shelf1", "shelf2"): Basis.CLEAR})
    )
    assert _locks(restored)[rule_key("shelf1", "shelf2")] is Basis.CLEAR
    assert solve(restored) == solve(scanned)
    others = {
        key: lock
        for key, lock in _locks(restored).items()
        if key != rule_key("shelf1", "shelf2")
    }
    assert set(others.values()) == {None}


def _plinth_unit() -> Unit:
    """A column over a plinth void, which a scan locks beside the bays."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 954.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Void(size_mm=100.0, lock=Basis.CLEAR, id="plinth"),
                _b("bottom"),
                Bay(size_mm=400.0, id="lower"),
                _b("shelf"),
                Bay(size_mm=400.0, id="upper"),
                _b("top"),
            ],
        ),
    )


def test_with_no_record_the_scans_locks_stand() -> None:
    scanned = _plinth_unit()
    assert with_stored_rules(scanned, None) is scanned


def test_a_record_is_the_whole_lock_state() -> None:
    """A region the record does not name is unlocked, the scan's lock on a
    plinth void included."""
    scanned = _plinth_unit()
    restored = with_stored_rules(
        scanned, StoredRules({rule_key("shelf", "top"): Basis.CLEAR})
    )
    locks = _locks(restored)
    assert locks[rule_key(None, "bottom")] is None
    assert locks[rule_key("shelf", "top")] is Basis.CLEAR
    assert locks[rule_key("bottom", "shelf")] is None
    assert solve(restored) == solve(scanned)
    assert set(_locks(with_stored_rules(scanned, StoredRules({}))).values()) == {None}


def test_an_unlocked_void_stays_unlocked_across_a_rescan() -> None:
    scanned = _plinth_unit()
    edited = unlock(scanned, "plinth")
    restored = with_stored_rules(scanned, parse_rules(rules_to_json(edited)))
    assert _locks(restored)[rule_key(None, "bottom")] is None
    kept = with_stored_rules(scanned, parse_rules(rules_to_json(scanned)))
    assert _locks(kept)[rule_key(None, "bottom")] is Basis.CLEAR


def test_a_stored_spacing_with_no_board_after_it_locks_its_clear_size() -> None:
    scanned = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                _b("left"),
                Bay(size_mm=300.0, id="bay"),
                Void(size_mm=282.0, id="void"),
            ],
        ),
    )
    restored = with_stored_rules(
        scanned, StoredRules({rule_key("left", None): Basis.WITH_NEXT})
    )
    assert _locks(restored)[rule_key("left", None)] is Basis.CLEAR


# --- Intent survival across a rescan: the point of the module. ----------------


def test_a_rescan_alone_locks_no_compartment() -> None:
    rescanned = _rescan_with_board_moved(_closed_box_unit(Basis.CLEAR))
    assert set(_locks(rescanned).values()) == {None}


def test_round_trip_recovers_a_locked_bay() -> None:
    original = _closed_box_unit(Basis.CLEAR)
    restored = _restored(original, _rescan_with_board_moved(original))
    assert _locks(restored) == _locks(original)
    _assert_same_spaces(restored, original)


def test_round_trip_recovers_a_spacing_a_scan_always_loses() -> None:
    original = _with_next_unit()
    rescanned = _rescan_with_board_moved(original)
    assert _locks(rescanned)[rule_key(None, "shelf")] is None
    restored = _restored(original, rescanned)
    assert _locks(restored) == _locks(original)
    _assert_same_spaces(restored, original)


def test_renamed_bounding_board_leaves_its_regions_unlocked() -> None:
    """Renaming "shelf2" invalidates the keys of the two regions it bounds;
    those come back unlocked rather than the call raising, while every other
    region still recovers its stored lock."""
    original = _closed_box_unit(Basis.CLEAR)
    serialized = rules_to_json(original)
    rescanned = _rescan_with_board_moved(original)

    def rename(region: Region) -> Region:
        if not isinstance(region, Division):
            return region
        items: list[Item] = []
        for item in region.items:
            if not isinstance(item, Board):
                items.append(rename(item))
            elif item.id == "shelf2":
                items.append(dataclasses.replace(item, id="shelf2_renamed"))
            else:
                items.append(item)
        return dataclasses.replace(region, items=items)

    renamed = dataclasses.replace(rescanned, root=rename(rescanned.root))
    restored = with_stored_rules(renamed, rules_from_json(serialized))
    assert _locks(restored)[rule_key("shelf1", "shelf2_renamed")] is None
    stored = with_stored_rules(
        renamed, StoredRules({rule_key("shelf1", "shelf2_renamed"): Basis.CLEAR})
    )
    assert _locks(stored)[rule_key("shelf1", "shelf2_renamed")] is Basis.CLEAR


# --- geometry wins on a rescan (bug-007) ------------------------------------


def test_a_rescan_keeps_a_hand_moved_shelf_where_it_was_moved() -> None:
    original = _closed_box_unit()
    rescanned = _rescan_with_board_moved(original, "shelf1", -60.0)
    restored = _restored(original, rescanned)
    shelf_z_mm = solve(rescanned)["shelf1"].origin.z_mm
    assert solve(restored)["shelf1"].origin.z_mm == pytest.approx(shelf_z_mm)
    assert solve(original)["shelf1"].origin.z_mm == pytest.approx(shelf_z_mm + 60.0)


def test_a_locked_bay_takes_its_scanned_size() -> None:
    original = _closed_box_unit(Basis.CLEAR)
    rescanned = _rescan_with_board_moved(original, "shelf2", 10.0)
    restored = _restored(original, rescanned)
    bay2_id = region_keys(restored)[rule_key("shelf1", "shelf2")]
    assert solve(restored)[bay2_id].size.z_mm == pytest.approx(437.5)
    assert _locks(restored)[rule_key("shelf1", "shelf2")] is Basis.CLEAR
    _assert_same_spaces(restored, rescanned)


def test_a_locked_spacing_keeps_its_basis_at_its_scanned_size() -> None:
    original = _with_next_unit()
    rescanned = _rescan_with_board_moved(original, "shelf", 10.0)
    restored = _restored(original, rescanned)
    spaced_id = region_keys(restored)[rule_key(None, "shelf")]
    assert _locks(restored)[rule_key(None, "shelf")] is Basis.WITH_NEXT
    assert solve(restored)[spaced_id].size.z_mm == pytest.approx(392.0)
    _assert_same_spaces(restored, rescanned)


def test_region_keys_find_each_region_again_after_a_rescan() -> None:
    original = _closed_box_unit()
    rescanned = _rescan_with_board_moved(original)
    before, after = region_keys(original), region_keys(rescanned)
    assert before.keys() == after.keys()
    assert before[rule_key("shelf1", "shelf2")] == "bay2"
    spaces_before, spaces_after = solve(original), solve(rescanned)
    for key, region_id in before.items():
        assert spaces_before[region_id] == spaces_after[after[key]], key


# --- constraints in the record (sh-048) ------------------------------------


def _inner_column(unit: Unit) -> Division:
    """The closed box's stack of four bays."""
    root = unit.root
    assert isinstance(root, Division)
    middle = root.items[1]
    assert isinstance(middle, Division)
    column = middle.items[1]
    assert isinstance(column, Division) and column.axis is Axis.Z
    return column


def _bay_ids(unit: Unit) -> list[str]:
    return [i.id for i in _inner_column(unit).items if not isinstance(i, Board)]


def _constrained(box: Unit, *constraints: Constraint) -> Unit:
    return dataclasses.replace(box, constraints=constraints)


def _equal(unit: Unit, first: int, second: int, *, active: bool = True) -> Equal:
    bays = _bay_ids(unit)
    return Equal(region_ids=(bays[first], bays[second]), active=active)


def _keyed(unit: Unit) -> list[tuple[str, ...]]:
    """Each constraint as the keys of its regions, which survive a rescan."""
    keys = {region_id: key for key, region_id in region_keys(unit).items()}
    return [
        tuple(keys[region_id] for region_id in constraint_regions(unit, constraint))
        for constraint in unit.constraints
    ]


def test_rules_to_json_emits_each_constraint_by_its_keys() -> None:
    box = _closed_box_unit()
    column = _inner_column(box).id
    unit = _constrained(
        box,
        _equal(box, 0, 2),
        EvenSpacing(run_id=column, start=RunEnd.START, end=RunEnd.END, active=False),
        EvenSpacing(run_id=box.root.id, start="bottom", end="top"),
    )
    doc = json.loads(rules_to_json(unit))
    assert doc["locks"] == {}
    assert doc["constraints"] == [
        {
            "kind": "equal",
            "basis": "clear",
            "active": True,
            "openings": [rule_key(None, "shelf1"), rule_key("shelf2", "shelf3")],
        },
        {
            "kind": "even_spacing",
            "basis": "clear",
            "active": False,
            "run": rule_key("left", "right"),
            "start": "~start",
            "end": "~end",
        },
        {
            "kind": "even_spacing",
            "basis": "clear",
            "active": True,
            "run": "~root",
            "start": "bottom",
            "end": "top",
        },
    ]


def test_constraints_survive_a_rescan_through_the_record() -> None:
    box = _closed_box_unit()
    original = _constrained(
        box,
        _equal(box, 0, 2),
        EvenSpacing(run_id=_inner_column(box).id, start="shelf1", end=RunEnd.END),
    )
    rescanned = _rescan_with_board_moved(original)
    restored = _restored(original, rescanned)
    assert _keyed(restored) == _keyed(original)
    assert [c.active for c in restored.constraints] == [True, True]
    _assert_same_spaces(restored, original)


def test_a_version_1_record_gives_no_constraints() -> None:
    text = json.dumps({"schema_version": 1, "locks": {"a|b": {"basis": "clear"}}})
    assert parse_rules(text) is None
    assert with_stored_rules(_closed_box_unit(), parse_rules(text)).constraints == ()


def test_opening_deactivates_a_constraint_the_boards_miss_beyond_the_clearance() -> (
    None
):
    box = _closed_box_unit()
    original = _constrained(box, _equal(box, 1, 2), _equal(box, 0, 3))
    rescanned = _rescan_with_board_moved(original, "shelf2", 50.0)
    restored, report = restore_rules(
        rescanned, parse_rules(rules_to_json(original)), DEFAULT_CLEARANCE_MM
    )
    moved, kept = restored.constraints
    assert (moved.active, kept.active) == (False, True)
    assert report == OpenReport(deactivated=(moved.id,))
    _assert_same_spaces(restored, rescanned)


def test_opening_keeps_a_constraint_the_boards_miss_within_the_clearance() -> None:
    box = _closed_box_unit()
    original = _constrained(box, _equal(box, 1, 2))
    rescanned = _rescan_with_board_moved(original, "shelf2", 1.0)
    restored, report = restore_rules(
        rescanned, parse_rules(rules_to_json(original)), DEFAULT_CLEARANCE_MM
    )
    (equal,) = restored.constraints
    assert equal.active
    assert report.empty
    _assert_same_spaces(restored, rescanned)


def test_a_stored_deactivated_constraint_stays_deactivated_when_met() -> None:
    box = _closed_box_unit()
    original = _constrained(box, _equal(box, 1, 2, active=False))
    restored, report = restore_rules(
        _rescan_with_board_moved(original),
        parse_rules(rules_to_json(original)),
        DEFAULT_CLEARANCE_MM,
    )
    (equal,) = restored.constraints
    assert not equal.active
    assert report.empty


def _renamed_board(unit: Unit, old: str, new: str) -> Unit:
    def rename(region: Region) -> Region:
        if not isinstance(region, Division):
            return region
        items: list[Item] = []
        for item in region.items:
            if isinstance(item, Board):
                items.append(
                    dataclasses.replace(item, id=new) if item.id == old else item
                )
            else:
                items.append(rename(item))
        return dataclasses.replace(region, items=items)

    return dataclasses.replace(unit, root=rename(unit.root))


def test_opening_drops_a_constraint_whose_key_or_end_board_is_gone() -> None:
    box = _closed_box_unit()
    column = _inner_column(box).id
    original = _constrained(
        box,
        _equal(box, 2, 3),
        _equal(box, 1, 2),
        EvenSpacing(run_id=column, start="shelf1", end=RunEnd.END),
        EvenSpacing(run_id=column, start=RunEnd.START, end="shelf3"),
    )
    gone = _renamed_board(_rescan_with_board_moved(original), "shelf1", "Box001")
    restored, report = restore_rules(
        gone, parse_rules(rules_to_json(original)), DEFAULT_CLEARANCE_MM
    )
    assert report == OpenReport(dropped=2)
    equal, spacing = restored.constraints
    assert isinstance(equal, Equal) and isinstance(spacing, EvenSpacing)
    assert spacing.end == "shelf3"


def test_opening_with_no_record_keeps_the_scan_and_reports_nothing() -> None:
    unit = _closed_box_unit()
    assert restore_rules(unit, None, DEFAULT_CLEARANCE_MM) == (unit, OpenReport())
