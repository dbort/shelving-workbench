---
id: sh-014
title: "Scanning: geometry to a region model"
current_agent: user
current_phase: user_signoff
review_rejections: 2
blocked_by: [sh-013]
---

# sh-014: Scanning: geometry to a region model

## Summary
Read a layout out of geometry: axis-aligned boxes in, a `Unit` or a refusal
naming the offending objects out. Detects the elevation plane, cuts at every
line no board crosses, treats sub-clearance gaps as joints rather than
compartments, and separates space enclosed by boards from space open to the
outside. Carries what it could not read rather than dropping it, because a
missing board does not fail a scan, it makes enclosed bays read as open.
Milestone M5, part 1 of 2.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `shelving_core/scan.py` exports `Box`, `Skipped`, `ScanError`,
      `ScanResult`, `FacingEvidence`, `scan`, `detect_depth_axis`,
      `infer_facing`, `boxes_from_json`, `export_from_json`.
- [x] `scan(boxes, catalog, ...)` returns a `ScanResult` whose `unit` is a
      `shelving_core.layout.Unit`. There is NO second tree type: no `Open`,
      `Outside`, `Cut`, `Divide`, or `Node` in the module.
- [x] `Unit` carries `depth_axis: Axis | None` and `front_at_min: bool | None`,
      both defaulting to `None`, and `scan` fills both.
- [x] Every board's end gaps land in its `Insets`, on all four cross-section
      faces, and a scanned board shallower than the unit carries depth insets.
- [x] The four real fixtures live under `shelving_core/tests/fixtures/` and each
      has a test asserting its whole tree shape: `real_stair_step` (stepped
      outline with `Void` regions), `real_two_units` (two abutting units, with
      both seams appearing as adjacent `Board` items), `real_magicstart_f1`
      (sides running through, a 100 mm plinth `Void`, 1 mm shelf insets), and
      `real_notched_panel` (read as a `Skipped` record, not a board).
- [x] `spikes/plain_planks/` is untouched and its tests still pass.
- [x] Round trip: for at least three hand-built units, `scan(expand(unit))`
      reproduces the tree shape and every board's size and placement to 1e-6 mm.
- [x] `ScanError` carries the offending object names in an `objects` attribute
      and is raised for each of: an overlap, a board crossing a bay boundary, a
      region with no clean cut line, an empty region part enclosed and part
      open, a unit with no enclosed bay, a box with no single thin axis, and a
      thickness matching no catalog entry. One test each.
- [x] `ScanResult.skipped` carries parts the export could not read, and a test
      proves a unit scanned without a board it needs reports that board rather
      than succeeding quietly.
- [x] `mypy --strict` clean; `shelving_core` imports no FreeCAD
      (`tests/test_no_freecad.py` still passes).

## Frontier Advice

CRITICAL: `spikes/plain_planks/scan.py` is the worked algorithm and
`spikes/plain_planks/test_scan.py` its tests. COPY from them; do NOT move,
edit, or delete the spike. It is the only way to read real geometry while the
workbench has no commands, and M6 deletes it.

THE BIG TRANSLATION. The spike scans into its own tree (`Open`, `Outside`,
`Cut`, `Divide`) and converts to the model separately, because the carcass
could not express what it found. The region model can. Build the `Unit`
DIRECTLY and delete the intermediate entirely. The mapping is exact:
- spike `Open` becomes `layout.Bay`
- spike `Outside` becomes `layout.Void`
- spike `Divide` becomes `layout.Division`, whose `axis` is a real
  `layout.Axis` rather than a two-valued orientation
- spike `Cut` becomes a `layout.Board`, with its two end clearances becoming
  two of the four `Insets`
- the spike's `to_carcass`, `_bay`, `_split`, `_has_open` and `Node` have no
  equivalent; do not port them

THE MODEL IS 3D (sh-013). A region has a 3D extent, a division names an axis.
Scanning stays SINGLE-PLANE: detect the depth axis, divide only along the other
two, and never emit a division along the depth axis. A board's depth extent
relative to its region becomes its depth-axis `Insets`, which is how a shelf
shallower than its carcass survives the read.

BACKS AND FRONTS ARE SET ASIDE, NOT PLACED. A box thin through the depth axis
projects over the whole elevation rather than dividing it. Collect these into
`ScanResult.panels` and report them. Do NOT place them as boards in a
depth-axis division: a back set within the carcass and one sitting proud behind
it need different trees and scanning cannot tell them apart, which is M11's
question. Reported, never dropped.

MATERIALS. `scan` takes a `Catalog`. Match each board's measured thickness to
the entry within `snap_mm`; the unit's `default_material` is the entry matching
the most common thickness, and a board whose thickness differs carries its own
`material`. A thickness matching no entry raises `ScanError` naming the board.
Do NOT leave a material unset as a fallback: `None` already means "inherit the
default" and must not also mean "unknown".

RULES. Recover with the equal-siblings heuristic the spike already has: sibling
regions equal within `snap_mm` get `Fill`, the rest get `Fixed` at their solved
size. Every recovered `Fixed` gets `Basis.CLEAR`; a basis is not recoverable
from geometry, because a clear opening and a shelf spacing place the boards
identically. Stored intent overriding this is M7's problem, not this task's.

THE CUT RULE, unchanged from the spike and non-obvious enough to restate. A cut
is any line no board CROSSES, not a line some one board spans; cutting at a
board's own two faces is the case where the resulting slab holds one board.
Three filters keep it usable: a cut line must be a face of a board in THAT
region, or a neighbouring unit's shelf heights slice this region's empty space
into meaningless slabs; lines closer together than `clearance_mm` are one joint,
and the survivor is the face of a board thin along the cut axis, or a shelf held
a millimetre off each side turns its joint gaps into one-millimetre bays; and a
slab holding one board that does not reach across it recurses rather than
refusing, or a shelf that fills its own column but not the height of the region
that column came from is rejected.

FACING. Port `infer_facing` complete, including the rule that a proud panel of
stock thickness is a door while a proud panel much thinner than the stock is an
overlay back, and that those point opposite ways. That rule was twice wrong on
the first real example it met. `FacingEvidence` keeps its four members; unknown
is the normal answer, and `front_at_min` stays `None` when nothing says.

`ScanResult` is a frozen dataclass: `unit: Unit`, `panels: tuple[Box, ...]`,
`skipped: tuple[Skipped, ...]`, `facing_evidence: FacingEvidence`,
`thicknesses_mm: frozenset[float]`. No bare `tuple`/`dict`/`list` in the public
surface.

`Box` is the input record: `name: str`, `corner_mm: Vec3`, `size_mm: Vec3`.
Convert from the spike's plain float triples. `boxes_from_json` and
`export_from_json` read the export format (a `boxes` array and a `skipped`
array) and MUST keep the spike's duplicate handling: two entries sharing a
`name` collapse when identical and raise when they differ, because a selection
can reach one object by more than one path. Do NOT publish a JSON Schema for
this format; it is internal between the FreeCAD layer and the core, not
interop.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no
bare containers in signatures or public attributes, `mypy --strict` clean.
Shell stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`. The snap tolerance is 0.5 mm and the
joint clearance 3.0 mm, both module constants, both defaults on `scan`; real
geometry has coincident edges disagreeing by up to 0.09 mm, which is why the
snap is not tighter.

## Execution Plan

- [x] **Step 1** (`shelving_core/tests/fixtures/`): Create the directory with an `__init__.py` if the test layout needs one, and COPY (do not move) `real_stair_step.boxes.json`, `real_two_units.boxes.json`, `real_magicstart_f1.boxes.json`, and `real_notched_panel.inspect.json` from `spikes/plain_planks/`. Add a `README.md` in the fixtures directory naming, for each file, what it is and what it was exported from: a stepped unit from a real project, two abutting units from a loose selection that still carries pre-fix duplicates, a cabinet generated by Woodworking's `magicStart` variant F1, and the inspection of a notched panel from a superseded revision. State that these are byte copies of real exports and must not be hand-edited.

- [x] **Step 2** (`shelving_core/layout.py`, `shelving_core/tests/test_layout.py`): Add two fields to `Unit`, after `root` and before `id`: `depth_axis: Axis | None = None` and `front_at_min: bool | None = None`. Document on each that they are presentation, not structure: the model divides along any axis, and these say which axis a reader projects along and which end of it faces the viewer. Document that `None` means undetermined and that facing is usually undetermined, so any code deriving a left or a right must handle not knowing. Add construction tests covering both defaults and both set. Change nothing else in the module.

- [x] **Step 3** (`shelving_core/scan.py`, `shelving_core/tests/test_scan.py`): Create the module with the input surface only. Frozen `Box(name: str, corner_mm: Vec3, size_mm: Vec3)`. Frozen `Skipped(name: str, label: str, type: str, reason: str)` documenting that it is carried rather than discarded because a dropped board makes a unit succeed with a hole. `ScanError(ValueError)` with an `objects: tuple[str, ...]` attribute set from an iterable argument. `boxes_from_json(text) -> list[Box]` and `export_from_json(text) -> tuple[list[Box], list[Skipped]]` over the export format, collapsing identical duplicate names and raising `ValueError` naming the conflict when two entries share a name and differ. Tests: parse each fixture and assert its box count, assert the duplicate collapse on `real_two_units` (39 entries to 28 distinct), and assert the conflict raise. Additive and green on its own.

- [x] **Step 4** (`shelving_core/scan.py`, `shelving_core/tests/test_scan.py`): Add plane and facing. `detect_depth_axis(boxes) -> Axis` picking the axis with the smallest bounding-box extent, documented as a guess that a unit deeper than it is wide would fool. `FacingEvidence(enum.StrEnum)` with `GIVEN`, `PANEL`, `FLUSH_BACK`, `NONE`. `infer_facing(boxes, depth_axis, tol_mm) -> tuple[bool | None, FacingEvidence]` porting the spike's two signals: a depth-thin board proud of the members is a door when stock-thickness and an overlay back when much thinner, and those point opposite ways; failing that, the end the members sit flush with is the back. Tests: the magicStart fixture infers front at minimum from its 3 mm overlay back, flipping that board to stock thickness infers the opposite, the stair-step fixture infers from the inset, and a uniform-depth synthetic unit returns `None` with `NONE`. Additive and green on its own.

- [x] **Step 5** (`shelving_core/scan.py`): Add the grid and the region recursion, porting the spike's `_Grid`, `_snap_lines`, `_index_of`, `_contained`, `_clean_lines`, `_slab`, `_gap`, `_region`, and `_empty`, retargeted from the spike's 2D `Rect` to `Space` and from the spike's `Member` classification to a check against the detected depth axis. The recursion returns `layout.Region` directly: an enclosed empty region becomes `Bay`, one reaching the outside becomes `Void`, a slab holding one board that reaches across becomes `Board` with its four `Insets`, and a run of slabs becomes `Division` with a real `Axis`. Preserve every refusal the spike raises, with its message and its named objects.

- [x] **Step 6** (`shelving_core/scan.py`): Add material resolution, rule recovery, and the public `scan`. A private helper maps a measured thickness to a `MaterialId` within `snap_mm` and raises `ScanError` naming the board when nothing matches. A second recovers sibling rules by the equal-siblings heuristic, emitting `Fill` for a region another sibling matches within `snap_mm` and `Fixed(size, Basis.CLEAR)` otherwise. `ScanResult` as the frozen dataclass described in Frontier Advice. `scan(boxes, catalog, *, snap_mm=DEFAULT_SNAP_MM, clearance_mm=DEFAULT_CLEARANCE_MM, depth_axis=None, front_at_min=None, skipped=()) -> ScanResult`: detect the axis when not given, infer facing when not given, set aside the depth-thin boards into `panels`, build the tree, resolve materials, recover rules, and assemble the `Unit` with its `size_mm` from the members' bounding box and both presentation fields filled.
  > **Checkpoint:** `pixi run tests` must be green here (Steps 5 and 6 are one algorithm; the recursion has no caller until `scan` exists).

- [x] **Step 7** (`shelving_core/tests/test_scan.py`): Add the refusal suite, one test per case, each asserting the message substring and the named objects: two boards overlapping; a board crossing the boundary of the bay it lies in; a pinwheel of four boards with no clean cut line; an empty region part enclosed and part open to the outside; a shell with a gap so no enclosed bay exists; a cube with no single thin axis; a thickness present in no catalog entry. Add the skipped-part test: scan a unit with one board removed and assert the tree comes back with regions reported as `Void` that the complete unit reports as `Bay`, proving a dropped board changes the answer rather than failing.

- [x] **Step 8** (`shelving_core/tests/test_scan.py`): Add the round-trip suite. For at least three hand-built units, a closed box, a stepped unit, and a unit with a board in a second material, run `expand`, convert the `BoardSpec` list to `Box` records, `scan` it back, and assert the recovered tree has the same shape and that re-expanding reproduces every board's size and placement to 1e-6 mm. Assert that a `Fill` sibling set comes back as `Fill` and an unequal set comes back as `Fixed`.

- [x] **Step 9** (`shelving_core/tests/test_scan.py`): Add one test per real fixture asserting its whole tree. `real_magicstart_f1`: sides running the full height with floor, shelf and top captured between them, a 100 mm plinth `Void` below the floor, 1 mm insets on the shelf, the back in `panels`, front at minimum depth. `real_stair_step`: a top board over everything, three uprights under it, `Void` below each step, the two inner shelves under their own divider. `real_two_units`: both seams present as adjacent `Board` items, the units' two top boards side by side, and the notched panel appearing in `skipped` rather than as a board. `real_notched_panel`: its inspection record reads as a `Skipped` entry.

- [x] **Step 10** (`README.md`): Extend the Glossary with the scanning vocabulary, in the section's existing one-bullet-per-term shape: Box, Skipped, ScanError, ScanResult, FacingEvidence, depth axis, facing, snap tolerance, joint clearance, and the cut rule stated as one sentence. State under facing that unknown is the normal answer.
