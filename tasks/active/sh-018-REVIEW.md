# sh-018 Review — Round 1

**Verdict:** REJECTED

Checks: `pixi run tests` green (202 unit tests, `freecad_scan_smoke.py` 9/9,
`freecad_write_smoke.py` 12/12, `mypy --strict` clean over 44 source files,
formatting, workflow lints). Every `## Must Have` line is met by the diff
and exercised by a test. The rejection below is about one specific, real
behavior gap in an otherwise solid implementation, not about the checks or
the bulk of the Must Haves.

## On the deletion-rule interpretation

The Implementer's report says it read the Frontier Advice's "An object is a
deletion candidate ONLY if it carries the provenance properties AND is
absent from the tree. Anything untagged is left exactly where it is." as
scoped to the deletion decision only, not to matching, and made a matched
untagged object get adopted (tagged, geometry written, relabeled) rather
than left alone. I re-derived this independently rather than trusting the
report, and the core of it is correct and necessary, not merely defensible:

- The Must Have "A non-box part is read as a pinned board rather than
  skipped; apply moves it" is unconditional — it does not say "only if
  already tagged" — and `_classify` (`freecad/Shelving/container.py:255-289`)
  now reads a notched panel as part of the layout (`irregular=True`)
  instead of `Skipped`, so a literal "untagged is never touched" would make
  that Must Have unsatisfiable for exactly the object it describes. A
  narrow reading that scopes "left exactly where it is" to deletion, so a
  match can still move the object, is the only reading that keeps both
  passages true at once.
- The Must Have "Each board carries `ShelvingMaterial`, `ShelvingBornAs`,
  `ShelvingBornIn`, and `ShelvingIrregular`" says "each board," not "each
  board this call creates," and the smoke test enforces exactly that
  (`tools/freecad_write_smoke.py:412`, `properties.has_board_properties(shelf)`
  asserted true after `rescan_unit` adopts a previously-untagged shelf).
  Tagging provenance on a matched-but-untagged object is required by this
  Must Have's own text, not an extrapolation.
- This is well documented for a human reading the branch: `friction-018` in
  `.claude/docs/friction-log.md` lays out the contradiction and the
  resolution in full, and `write_container`'s own docstring
  (`freecad/Shelving/container.py:591-600`) and `WriteResult`'s docstring
  (`:551-559`) state the adoption behavior plainly.

So the matching/tagging half of the interpretation is not a coin flip the
Implementer got lucky on — it is close to the only reading that makes the
task file internally consistent, and it is properly recorded.

## Blocking findings

- **F1: adoption also silently overwrites a user-authored `Label`, which
  no Must Have requires and no test checks** (`freecad/Shelving/container.py:613-624`):
  inside the matched-object branch, `adopting` is true both when `obj`
  carries no provenance yet and when it is a copy; in either case the code
  unconditionally does `cast("_Placeable", obj).Label = labels[spec.node_id]`
  before folding `obj.Name` into `created`. For the copy case this is
  exactly what the Frontier Advice's "a copy is adopted, not rejected"
  paragraph asks for. For the first case — a hand-built object (the
  task's own worked example: a notched panel slotted into a real bay) that
  a user has already given a `Label` of their own — nothing in the task
  file asks for the `Label` to be touched at all, and the object does not
  need it touched: tagging provenance alone (already required, see above)
  is enough to make `has_board_properties(obj)` true, which means the very
  next apply no longer takes the `adopting` branch and the `Label` is
  never revisited again. Skipping the `Label` write on first adoption
  would satisfy every Must Have in this file, including "a user rename
  sticks," while the current code overwrites the one `Label` a user is
  most likely to have deliberately set — the notched-panel workflow the
  task file itself uses as its motivating example. This is also the
  primary path for irregular boards, not a corner case: any user who
  hand-builds a board, names it, and places it in a bay hits this on their
  first resize or rescan.

  This is not covered by a test. `test_irregular_board_moves_without_rewriting_its_shape`
  (`tools/freecad_write_smoke.py:389-428`) creates the notched shelf,
  asserts it lands in `adopt_result.created`, and asserts its board
  properties and shape survive a later move — it never reads `shelf.Label`
  before or after `rescan_unit` adopts it, so the overwrite has no
  assertion pinning it down one way or the other. Per the reviewer
  protocol, an unverified, user-visible, one-way side effect like this
  needs a real committed test, not a judgment call baked into code with no
  test proving what it does.

  Fix either direction, but make it deliberate and tested: (a) drop the
  `Label` write from the "matched, not yet tagged" half of `adopting`
  (keep it for the copy half, which the Frontier Advice explicitly
  covers) and add a test asserting a pre-set `Label` on a hand-built board
  survives its first adoption; or (b) keep the overwrite, but add a test
  that pins the current behavior down explicitly (assert the shelf's
  `Label` before adoption, then after, showing it changes) and add one or
  two lines to this task file's `## Frontier Advice` recording that a
  hand-built object's own `Label` is treated as workbench-generated
  scratch, not user intent, the first time it is swept into the tree —
  the friction log entry is not a substitute for that: it is a record of a
  workaround for this review cycle, not part of what the human at
  `user_signoff` is pointed at when deciding whether the shipped behavior
  is what they want. I lean toward (a): it is strictly safer, satisfies
  every Must Have as written, and nothing in the task file asks for a
  `Label` overwrite here. Either way, flag this specifically to the human
  at sign-off — it is a real, deliberate behavior choice beyond what the
  task file specifies, on data the user authored outside the workbench.

## Non-blocking notes

- **N1: `ContainerRecord.copied` is computed and never read**
  (`freecad/Shelving/container.py:130`, populated at `:178-179`): every
  caller of `read_container` (`freecad/Shelving/unit_ops.py:_rescanned_unit`,
  the two `commands/*.py` call sites, every smoke test) discards or ignores
  this field, and `write_container`'s own copy handling recomputes
  `properties.is_copy(obj, doc)` directly on each matched object rather
  than consulting it. Either wire it to an actual use or drop the field
  and the set-building it costs in `read_container`.
