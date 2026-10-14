"""Tests for the stored rule record."""

import dataclasses
import json
from collections.abc import Mapping

import pytest

from freecad.Shelving.core.expand import expand
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
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
    Weighted,
)
from freecad.Shelving.core.record import (
    RULE_RECORD_VERSION,
    region_keys,
    rule_key,
    rules_from_json,
    rules_to_json,
    with_stored_rules,
)
from freecad.Shelving.core.scan import Box, scan
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


# --- rules_to_json() ---------------------------------------------------------


def test_rules_to_json_emits_one_entry_per_non_root_region() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, id="bottom"),
            Division(
                axis=Axis.X,
                items=[
                    Board(thickness_mm=18.0, id="left"),
                    Bay(rule=Fixed(400.0), id="bay"),
                    Board(thickness_mm=18.0, id="right"),
                ],
                id="mid",
            ),
            Board(thickness_mm=18.0, id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(900.0, 300.0, 1800.0), root=root)
    doc = json.loads(rules_to_json(unit))
    assert doc["schema_version"] == RULE_RECORD_VERSION
    # "mid" (a Division) and "bay" are the two non-root regions; the root
    # itself contributes no entry.
    assert set(doc["rules"]) == {rule_key("bottom", "top"), rule_key("left", "right")}


def _bay_unit(rule: SizeRule) -> Unit:
    """A minimal unit with one region, "bay", whose rule is under test."""
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, id="lower"),
            Bay(rule=rule, id="bay"),
            Board(thickness_mm=18.0, id="upper"),
        ],
        id="root",
    )
    return Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=root)


def test_rules_to_json_preserves_fixed_basis_clear() -> None:
    unit = _bay_unit(Fixed(400.0, basis=Basis.CLEAR))
    doc = json.loads(rules_to_json(unit))
    key = rule_key("lower", "upper")
    assert doc["rules"][key] == {"type": "fixed", "size_mm": 400.0, "basis": "clear"}


def test_rules_to_json_preserves_fixed_basis_with_next() -> None:
    unit = _bay_unit(Fixed(400.0, basis=Basis.WITH_NEXT))
    doc = json.loads(rules_to_json(unit))
    key = rule_key("lower", "upper")
    assert doc["rules"][key] == {
        "type": "fixed",
        "size_mm": 400.0,
        "basis": "with_next",
    }


# --- rules_from_json() --------------------------------------------------------


@pytest.mark.parametrize(
    "rule",
    [
        Fixed(250.0, basis=Basis.CLEAR),
        Fixed(300.0, basis=Basis.WITH_NEXT),
        Weighted(2.5),
        Fill(),
    ],
)
def test_rules_from_json_round_trips_every_rule_variant(rule: SizeRule) -> None:
    unit = _bay_unit(rule)
    restored = rules_from_json(rules_to_json(unit))
    assert restored[rule_key("lower", "upper")] == rule


def _bad_record(rules: dict[str, object]) -> str:
    return json.dumps({"schema_version": RULE_RECORD_VERSION, "rules": rules})


def test_rules_from_json_raises_on_wrong_version() -> None:
    bad = json.dumps({"schema_version": RULE_RECORD_VERSION + 1, "rules": {}})
    with pytest.raises(ValueError, match="schema_version"):
        rules_from_json(bad)


def test_rules_from_json_raises_on_missing_key() -> None:
    """A ``fixed`` rule doc missing its required ``size_mm`` key."""
    bad = _bad_record({"k": {"type": "fixed", "basis": "clear"}})
    with pytest.raises(ValueError, match="size_mm"):
        rules_from_json(bad)


def test_rules_from_json_raises_on_malformed_rule_type() -> None:
    bad = _bad_record({"k": {"type": "bogus"}})
    with pytest.raises(ValueError, match="type"):
        rules_from_json(bad)


def test_rules_from_json_raises_on_non_numeric_size() -> None:
    bad = _bad_record({"k": {"type": "fixed", "size_mm": "wide", "basis": "clear"}})
    with pytest.raises(ValueError, match="size_mm"):
        rules_from_json(bad)


# --- with_stored_rules() ------------------------------------------------------


def _find_bay(region: Region, region_id: str) -> Bay:
    assert isinstance(region, Division)
    for item in region.items:
        if isinstance(item, Bay) and item.id == region_id:
            return item
    raise AssertionError(f"no Bay with id {region_id!r}")


def test_with_stored_rules_replaces_a_matching_rule() -> None:
    unit = _bay_unit(Fill())
    key = rule_key("lower", "upper")
    updated = with_stored_rules(unit, {key: Fixed(250.0, basis=Basis.CLEAR)})
    # The record says the bay is locked; the boards say how big it is.
    assert _find_bay(updated.root, "bay").rule == Fixed(864.0, basis=Basis.CLEAR)


def test_with_stored_rules_leaves_an_unmatched_region_rule_as_scanned() -> None:
    unit = _bay_unit(Fill())
    updated = with_stored_rules(unit, {"no-such-key": Fixed(250.0)})
    assert _find_bay(updated.root, "bay").rule == Fill()


def _strip_rules_item(item: Item) -> Item:
    return item if isinstance(item, Board) else _strip_rules(item)


def _strip_rules(region: Region) -> Region:
    """``region`` with every rule reset to a fixed value, so two trees that
    differ only in their rules compare equal: everything else a dataclass
    ``==`` would catch (ids, axes, board fields, tree shape) still counts."""
    if isinstance(region, Division):
        return dataclasses.replace(
            region,
            rule=Fill(),
            items=[_strip_rules_item(item) for item in region.items],
        )
    return dataclasses.replace(region, rule=Fill())


def test_with_stored_rules_returns_a_unit_whose_tree_is_otherwise_identical() -> None:
    unit = _bay_unit(Fill())
    key = rule_key("lower", "upper")
    updated = with_stored_rules(unit, {key: Fixed(250.0, basis=Basis.CLEAR)})
    assert _strip_rules(updated.root) == _strip_rules(unit.root)
    assert updated.size_mm == unit.size_mm
    assert updated.id == unit.id


# --- Intent survival: the point of the module. -------------------------------


def _b(role: str) -> Board:
    """A board whose id matches its role, standing in for what sh-018 makes
    true in the real pipeline: a board's id is its stable FreeCAD object
    name, which is also what a scanned board's role is read from."""
    return Board(thickness_mm=18.0, role=role, id=role)


def _closed_box_unit() -> Unit:
    """Four equal bays behind three shelves, every region ``Fill``: the
    rules a scan recovers on its own, with no stored record."""
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
                                Bay(id="bay1"),
                                _b("shelf1"),
                                Bay(id="bay2"),
                                _b("shelf2"),
                                Bay(id="bay3"),
                                _b("shelf3"),
                                Bay(id="bay4"),
                            ],
                        ),
                        _b("right"),
                    ],
                ),
                _b("top"),
            ],
        ),
    )


def _fixed_matching_siblings_unit() -> Unit:
    """The same four bays, but "bay2" is deliberately ``Fixed`` at exactly
    the size the other three solve to as ``Fill``: geometry alone cannot
    tell them apart, so a rescan flattens "bay2" to ``Fill`` too, and only
    the stored record recovers the original ``Fixed``."""
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
                                Bay(id="bay1"),
                                _b("shelf1"),
                                Bay(rule=Fixed(427.5, basis=Basis.CLEAR), id="bay2"),
                                _b("shelf2"),
                                Bay(id="bay3"),
                                _b("shelf3"),
                                Bay(id="bay4"),
                            ],
                        ),
                        _b("right"),
                    ],
                ),
                _b("top"),
            ],
        ),
    )


def _with_next_unit() -> Unit:
    """A closed box whose interior shelf spacing is quoted top face to top
    face (``Basis.WITH_NEXT``): "spaced_bay" covers itself plus "shelf". A
    clear opening and a ``WITH_NEXT`` spacing place their boards identically,
    so a rescan always recovers ``Basis.CLEAR``, at a different size since
    ``CLEAR`` excludes the following board's thickness."""
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
                                Bay(
                                    rule=Fixed(400.0, basis=Basis.WITH_NEXT),
                                    id="spaced_bay",
                                ),
                                _b("shelf"),
                                Bay(id="top_bay"),
                            ],
                        ),
                        _b("right"),
                    ],
                ),
                _b("top"),
            ],
        ),
    )


def _stabilize_board_ids(region: Region) -> Region:
    """``region`` with every ``Board``'s ``id`` replaced by its ``role``.

    A scanned board's ``id`` is a fresh uuid; ``role`` is what carries the
    box name (the original board's id, round-tripped through ``expand`` and
    ``scan``) across the rescan. sh-018 makes a board's real ``id`` equal to
    its stable FreeCAD object name; this stands in for that step so the
    record's key-stability guarantee is exercised without FreeCAD.
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


def _rescan_unit(unit: Unit) -> Unit:
    """``unit`` taken to boards and back through ``scan``, with board ids
    stabilized per :func:`_stabilize_board_ids`."""
    specs = expand(unit)
    boxes = [Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size) for s in specs]
    rescanned = scan(boxes).unit
    return dataclasses.replace(rescanned, root=_stabilize_board_ids(rescanned.root))


def _rule_map(unit: Unit) -> Mapping[str, SizeRule]:
    return rules_from_json(rules_to_json(unit))


def test_round_trip_all_equal_bays() -> None:
    original = _closed_box_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original)
    assert _rule_map(rescanned) == original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _rule_map(restored) == original_rules


def test_round_trip_recovers_a_fixed_bay_the_heuristic_flattens_to_fill() -> None:
    original = _fixed_matching_siblings_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original)
    assert _rule_map(rescanned) != original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _rule_map(restored) == original_rules


def test_round_trip_recovers_a_with_next_basis_a_scan_always_loses() -> None:
    original = _with_next_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original)
    assert _rule_map(rescanned) != original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _intent(restored) == _intent(original)
    assert _rule_map(restored)[rule_key(None, "shelf")] == Fixed(
        400.0, basis=Basis.WITH_NEXT
    )
    _assert_same_spaces(restored, original)


def _intent(unit: Unit) -> Mapping[str, Basis | None]:
    """Each region's basis when it is locked, ``None`` when unlocked: what a
    record carries across a rescan."""
    return {
        key: rule.basis if isinstance(rule, Fixed) else None
        for key, rule in _rule_map(unit).items()
    }


def _assert_same_spaces(a: Unit, b: Unit) -> None:
    """Every board of ``a`` and ``b`` in the same place; region ids differ
    across a rescan, board ids do not."""
    spaces_a, spaces_b = solve(a), solve(b)
    for board_id in _board_ids(a.root):
        assert spaces_a[board_id].origin.z_mm == pytest.approx(
            spaces_b[board_id].origin.z_mm
        ), board_id
        assert spaces_a[board_id].origin.x_mm == pytest.approx(
            spaces_b[board_id].origin.x_mm
        ), board_id


def _board_ids(region: Region) -> list[str]:
    if not isinstance(region, Division):
        return []
    found: list[str] = []
    for item in region.items:
        found += [item.id] if isinstance(item, Board) else _board_ids(item)
    return found


def _rename_board_id(unit: Unit, old_id: str, new_id: str) -> Unit:
    def walk(region: Region) -> Region:
        if not isinstance(region, Division):
            return region
        new_items: list[Item] = []
        for item in region.items:
            if isinstance(item, Board):
                new_items.append(
                    dataclasses.replace(item, id=new_id) if item.id == old_id else item
                )
            else:
                new_items.append(walk(item))
        return dataclasses.replace(region, items=new_items)

    return dataclasses.replace(unit, root=walk(unit.root))


def test_renamed_bounding_board_falls_back_to_scanned_rule_without_raising() -> None:
    """Renaming "shelf2" invalidates the keys of the two regions it bounds
    ("bay2" and "bay3"); those two keep whatever rule the rescan gave them
    rather than the call raising, while every other region still recovers
    its original stored rule."""
    original = _fixed_matching_siblings_unit()
    serialized = rules_to_json(original)
    rescanned = _rescan_unit(original)
    renamed = _rename_board_id(rescanned, old_id="shelf2", new_id="shelf2_renamed")

    scanned_rules = _rule_map(renamed)
    restored_rules = _rule_map(with_stored_rules(renamed, rules_from_json(serialized)))

    affected_keys = [
        rule_key("shelf1", "shelf2_renamed"),
        rule_key("shelf2_renamed", "shelf3"),
    ]
    for key in affected_keys:
        assert restored_rules[key] == scanned_rules[key]

    original_rules = _rule_map(original)
    unaffected_keys = [
        rule_key("bottom", "top"),
        rule_key("left", "right"),
        rule_key(None, "shelf1"),
        rule_key("shelf3", None),
    ]
    for key in unaffected_keys:
        assert restored_rules[key] == original_rules[key]


# --- geometry wins on a rescan (bug-007) ------------------------------------


def _rescan_with_board_moved(unit: Unit, board_id: str, up_mm: float) -> Unit:
    """:func:`_rescan_unit` after ``board_id`` was moved ``up_mm`` by hand."""
    boxes: list[Box] = []
    for spec in expand(unit):
        corner = spec.placement
        if spec.node_id == board_id:
            corner = Vec3(corner.x_mm, corner.y_mm, corner.z_mm + up_mm)
        boxes.append(Box(name=spec.node_id, corner_mm=corner, size_mm=spec.size))
    rescanned = scan(boxes).unit
    return dataclasses.replace(rescanned, root=_stabilize_board_ids(rescanned.root))


def _box_with_bay2(rule: SizeRule) -> Unit:
    """:func:`_closed_box_unit` with "bay2" ruled by ``rule``."""
    unit = _closed_box_unit()
    assert isinstance(unit.root, Division)
    shell = unit.root.items[1]
    assert isinstance(shell, Division)
    column = shell.items[1]
    assert isinstance(column, Division)
    column.items[2] = Bay(rule=rule, id="bay2")
    return unit


def test_a_rescan_keeps_a_hand_moved_shelf_where_it_was_moved() -> None:
    original = _closed_box_unit()
    record = rules_from_json(rules_to_json(original))
    rescanned = _rescan_with_board_moved(original, "shelf1", -60.0)
    restored = with_stored_rules(rescanned, record)
    # Every stored region is unlocked, so each keeps the rule the scan
    # recovered from the moved boards.
    assert _rule_map(restored) == _rule_map(rescanned)
    shelf_z_mm = solve(rescanned)["shelf1"].origin.z_mm
    assert solve(restored)["shelf1"].origin.z_mm == pytest.approx(shelf_z_mm)
    assert solve(original)["shelf1"].origin.z_mm == pytest.approx(shelf_z_mm + 60.0)


def test_a_locked_bay_takes_its_scanned_size() -> None:
    original = _box_with_bay2(Fixed(250.0, basis=Basis.CLEAR))
    record = rules_from_json(rules_to_json(original))
    rescanned = _rescan_with_board_moved(original, "shelf2", 10.0)
    restored = with_stored_rules(rescanned, record)
    rules = _rule_map(restored)
    bay2 = rules[rule_key("shelf1", "shelf2")]
    assert isinstance(bay2, Fixed)
    assert bay2.size_mm == pytest.approx(260.0)
    assert bay2.basis is Basis.CLEAR
    for key in (rule_key(None, "shelf1"), rule_key("shelf2", "shelf3")):
        assert rules[key] == _rule_map(rescanned)[key]
    _assert_same_spaces(restored, rescanned)


def test_a_locked_spacing_keeps_its_basis_at_its_scanned_size() -> None:
    original = _with_next_unit()
    record = rules_from_json(rules_to_json(original))
    rescanned = _rescan_with_board_moved(original, "shelf", 10.0)
    restored = with_stored_rules(rescanned, record)
    spaced = _rule_map(restored)[rule_key(None, "shelf")]
    assert isinstance(spaced, Fixed)
    assert spaced.basis is Basis.WITH_NEXT
    assert spaced.size_mm == pytest.approx(410.0)
    _assert_same_spaces(restored, rescanned)


def test_an_unlocked_region_the_scan_fixed_shares_at_its_scanned_size() -> None:
    """A scan fixes a plinth void beside compartments; a record that says it
    was unlocked unlocks it at the weight that keeps it where it is."""
    scanned = Unit(
        size_mm=Vec3(600.0, 300.0, 954.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Void(rule=Fixed(100.0), id="plinth"),
                _b("bottom"),
                Bay(id="lower"),
                _b("shelf"),
                Bay(id="upper"),
                _b("top"),
            ],
        ),
    )
    stored = {rule_key(None, "bottom"): Fill()}
    restored = with_stored_rules(scanned, stored)
    plinth = _rule_map(restored)[rule_key(None, "bottom")]
    # Each Fill bay is 400 mm between 18 mm boards, so one unit of weight
    # is 400 mm.
    assert plinth == Weighted(weight=0.25)
    _assert_same_spaces(restored, scanned)
    assert solve(restored)["plinth"].size.z_mm == pytest.approx(100.0)


def test_an_unlocked_region_with_no_unlocked_sibling_takes_its_size_as_weight() -> None:
    scanned = _bay_unit(Fixed(864.0))
    restored = with_stored_rules(scanned, {rule_key("lower", "upper"): Fill()})
    assert _find_bay(restored.root, "bay").rule == Weighted(weight=864.0)


def test_a_unit_that_does_not_solve_comes_back_unchanged() -> None:
    """Its caller's own solve then reports the boards' error."""
    unsolvable = _bay_unit(Fixed(1000.0))
    restored = with_stored_rules(unsolvable, {rule_key("lower", "upper"): Fill()})
    assert restored is unsolvable


def test_region_keys_find_each_region_again_after_a_rescan() -> None:
    original = _closed_box_unit()
    rescanned = _rescan_unit(original)
    before, after = region_keys(original), region_keys(rescanned)
    assert before.keys() == after.keys()
    assert before[rule_key("shelf1", "shelf2")] == "bay2"
    spaces_before, spaces_after = solve(original), solve(rescanned)
    for key, region_id in before.items():
        assert spaces_before[region_id] == spaces_after[after[key]], key
