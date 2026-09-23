# sh-019 Review — Round 2

**Verdict:** REJECTED

Raised after the branch had already been approved: the user found this
during manual sign-off testing and asked for it to be fixed inside sh-019
rather than deferred. `pixi run tests` is green on the branch tip (exit 0,
`All checks passed!`), so this round is one behavioral finding, not a
broken build.

## Blocking findings

- **F1: one incomplete catalog entry blocks every catalog-touching command
  in the document, not just uses of that entry**
  (`freecad/Shelving/catalog.py:146`, `freecad/Shelving/commands/reflow_all.py:57`,
  `freecad/Shelving/commands/scan.py:94`,
  `freecad/Shelving/commands/resize_unit.py:146`,
  `freecad/Shelving/unit_ops.py:84`): `add_entry` leaves a new entry at
  `Thickness` `0 mm` until the user edits it, and `read_catalog` is
  required to raise on a non-positive `Thickness` (this task's own Must
  Have). But `read_catalog` builds the whole document's `Catalog` in one
  call with no partial-build option, and `Shelving_ReflowAll`,
  `Shelving_Scan`, `Shelving_ResizeUnit`, and `Shelving_CreateUnit` each
  call `read_catalog(ensure_catalog(doc))` once up front, before touching
  any unit. So one unfinished entry anywhere in the catalog refuses all
  four commands for every unit in the document, including units that would
  never reference the unfinished entry, and the only signal is a
  `REFUSED: <ValueError>` line in the Report view naming the catalog entry
  rather than the command or the unit the user actually ran.

  Found by the user during manual sign-off on this branch: change a board
  to a valid material and reflow (works), run **Add Material** and leave
  the new entry unedited, change a different board back to an
  already-valid material and reflow (refused, board unchanged, only a
  Report-view line to say so), delete the unfinished entry, reflow again
  (succeeds). Root-caused and written up as `bug-002` in
  `.claude/docs/bug-log.md` on this same branch; read that entry for the
  full trace rather than re-deriving it.

  **This is in scope for sh-019.** `bug-002`'s own ad-hoc-vs-task call
  says `sh-XXX task`, meaning a separate future task; the user has since
  decided it must be fixed before this branch merges, so treat it as a
  normal blocking finding for this round and ignore that part of the
  entry. Per `.claude/docs/bug-log.md` § Solving a bug, delete the
  `bug-002` entry in the same commit that fixes it (leave `next_id`
  alone) — the task file and this branch's history become the durable
  record.

  This needs a design decision, not a mechanical patch, and the decision
  is yours to make and mine to review. Candidate shapes, none of them
  mandated:
  - Validate lazily: build or validate only the entries a command's actual
    boards/units reference, so an unrelated incomplete entry never blocks a
    command that never touches it.
  - Keep eager whole-catalog validation, but make the refusal attributable
    to the command and unit the user ran, not a bare entry name in the
    Report view.
  - Anything else you judge better, as long as one incomplete material
    stops blocking use of every other, already-valid material.

  Whichever shape you pick, state the reasoning in the commit message, and
  cover it with a committed automated test in `pixi run tests` rather than
  a manual check: at minimum a case where a document holds a valid unit
  plus an unedited `add_entry` result, and a reflow (or scan/resize) of
  that unit still succeeds. Note that
  `tools/freecad_catalog_smoke.py:224`
  (`_case_add_entry_is_blank_and_blocks_read_catalog_until_edited`)
  currently asserts the defective behavior as if it were the contract, so
  it has to be revised, not merely added to; keep whatever part of it
  still expresses a real requirement (an entry with a zero `Thickness` is
  not usable as a material, and editing it makes it usable).

## Non-blocking notes

- **N1: M8 manual-QA case 3 never exercises the intermediate state**
  (`docs/manual-qa.md:351`): the steps have the user run **Add Material**
  and immediately edit the new entry, so the window in which the entry is
  incomplete is never visible in the doc. Once F1 is fixed, extend that
  case to say what a user should expect from another command run while an
  entry is still blank, so the intended behavior is documented rather than
  implied.
