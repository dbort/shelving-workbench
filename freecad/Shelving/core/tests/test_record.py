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
    Weighted,
)
from freecad.Shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.Shelving.core.record import (
    RULE_RECORD_VERSION,
    rule_key,
    rules_from_json,
    rules_to_json,
    with_stored_rules,
)
from freecad.Shelving.core.scan import Box, scan

PLY = MaterialId("ply18")
CATALOG = Catalog(entries={PLY: MaterialEntry(PLY, "ply 18", 18.0, "plywood")})


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
            Board(id="bottom"),
            Division(
                axis=Axis.X,
                items=[
                    Board(id="left"),
                    Bay(rule=Fixed(400.0), id="bay"),
                    Board(id="right"),
                ],
                id="mid",
            ),
            Board(id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(900.0, 300.0, 1800.0), default_material=PLY, root=root)
    doc = json.loads(rules_to_json(unit))
    assert doc["schema_version"] == RULE_RECORD_VERSION
    # "mid" (a Division) and "bay" are the two non-root regions; the root
    # itself contributes no entry.
    assert set(doc["rules"]) == {rule_key("bottom", "top"), rule_key("left", "right")}


def _bay_unit(rule: SizeRule) -> Unit:
    """A minimal unit with one region, "bay", whose rule is under test."""
    root = Division(
        axis=Axis.Z,
        items=[Board(id="lower"), Bay(rule=rule, id="bay"), Board(id="upper")],
        id="root",
    )
    return Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=PLY, root=root)


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
    assert _find_bay(updated.root, "bay").rule == Fixed(250.0, basis=Basis.CLEAR)


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
    assert updated.default_material == unit.default_material
    assert updated.id == unit.id


# --- Intent survival: the point of the module. -------------------------------


def _b(role: str) -> Board:
    """A board whose id matches its role, standing in for what sh-018 makes
    true in the real pipeline: a board's id is its stable FreeCAD object
    name, which is also what a scanned board's role is read from."""
    return Board(role=role, id=role)


def _closed_box_unit() -> Unit:
    """Four equal bays behind three shelves. The bays themselves are what
    the equal-siblings heuristic is built for and recover as ``Fill``
    correctly; the two outer divisions (each an only child within its own
    parent's run, nothing to compare against) do not and recover as
    ``Fixed`` instead of their original ``Fill``."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        default_material=PLY,
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
        default_material=PLY,
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
        default_material=PLY,
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


def _rescan_unit(unit: Unit, catalog: Catalog) -> Unit:
    """``unit`` taken to boards and back through ``scan``, with board ids
    stabilized per :func:`_stabilize_board_ids`."""
    specs = expand(unit, catalog)
    boxes = [Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size) for s in specs]
    rescanned = scan(boxes, catalog).unit
    return dataclasses.replace(rescanned, root=_stabilize_board_ids(rescanned.root))


def _rule_map(unit: Unit) -> Mapping[str, SizeRule]:
    return rules_from_json(rules_to_json(unit))


def test_round_trip_all_equal_bays() -> None:
    original = _closed_box_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original, CATALOG)
    # The two outer, only-child divisions recover as Fixed rather than their
    # original Fill; see _closed_box_unit's docstring.
    assert _rule_map(rescanned) != original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _rule_map(restored) == original_rules


def test_round_trip_recovers_a_fixed_bay_the_heuristic_flattens_to_fill() -> None:
    original = _fixed_matching_siblings_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original, CATALOG)
    assert _rule_map(rescanned) != original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _rule_map(restored) == original_rules


def test_round_trip_recovers_a_with_next_basis_a_scan_always_loses() -> None:
    original = _with_next_unit()
    original_rules = _rule_map(original)
    rescanned = _rescan_unit(original, CATALOG)
    assert _rule_map(rescanned) != original_rules

    restored = with_stored_rules(rescanned, rules_from_json(rules_to_json(original)))
    assert _rule_map(restored) == original_rules


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
    rescanned = _rescan_unit(original, CATALOG)
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
