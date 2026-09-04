# sh-011 Review — Round 4 (sign-off re-review)

**Verdict:** REJECTED

Re-review of the fix commit `2f96a4d` against Round 3's findings. This is still a
sign-off re-review, not a rejection-loop round: `review_rejections` stays at **1**
and this round does not count toward the cap of 3.

`pixi run tests`: **green**, exit 0. `check_lock_paths` OK, ruff lint clean, 72
files already formatted, `mypy --strict` clean over 29 source files, shellcheck
OK, vendor drift OK, 146 pytest passed, workflow lint OK (actionlint, zizmor,
dependabot schema, 7/7 action pins), both `freecadcmd` smokes printed their
markers (`shelving workbench import OK`, `shelving object layer OK`).

Round 3's findings are all resolved. `2f96a4d` touched only
`docs/freecadcmd-notes.md` and the two task files — no code, no lock, no
tooling — and introduced no new problems:

- **F1 (resolved):** the friction-log deletion is now recorded in the task file's
  `## Sign-off addendum`, Round B
  (`tasks/active/sh-011-freecad-object-layer.md:55-60`), naming the removed entry
  verbatim, attributing the removal to the user, and pointing at
  `docs/freecadcmd-notes.md` for the surviving behavioral fact. That is the
  second of the two remedies Round 3 offered; the entry is correctly not
  restored.
- **F2 (resolved):** all three literal module paths in sh-012 now read
  `default_catalog` (`:60`, `:104`, `:207`). A full `catalog` grep over that file
  shows the only other hits are concept mentions that are correct as written:
  "in-code default catalog" (`:17`), the `DEFAULT_CATALOG` symbol (`:74`,
  `:132`), the manual-QA catalog (`:152-153`, `:305`), and M4's catalog document
  object (`:194-195`). No stale `freecad.shelving.catalog` /
  `freecad/shelving/catalog.py` remains.
- **N1 (done):** `docs/freecadcmd-notes.md:6` now reads "most are handled in the
  code cited below".
- **N3 (done):** the addendum's Round B lists the `add_plank` / `Plank(obj)`
  comment (`tasks/active/sh-011-freecad-object-layer.md:61-63`).
- **N2:** no action, as agreed.

One blocking finding remains, and it is a miss of mine from Round 3 rather than
anything `2f96a4d` did wrong. It is the same defect class as F2, on the same
sibling file, created by the same batch of sign-off edits: F2 was the debt the
`catalog` rename (`69e9303`) owed sh-012's plan, and F3 below is the debt the
probe removal (`db325f6`) owes it. I scoped Round 3's F2 to the rename and did
not sweep the file for the probe removal's fallout; that was incomplete.

## Blocking findings

- **F3: the probe removal leaves `sh-012`'s plan instructing an Implementer to
  preserve a probe that no longer exists**
  (`tasks/active/sh-012-shelving-unit-container.md:127`, `:302`): both lines tell
  the sh-012 Implementer to keep sh-011's `App::Part` probe when extending
  `tools/freecad_object_smoke.py`. `:127` is a `## Must Have` checkbox — "Add a
  section, keeping sh-011's checks and the `App::Part` probe, that:" — and `:302`
  is Execution Plan Step 5 — "Keep sh-011's checks, the probe, and the marker."
  `db325f6` deleted the probe at the user's request; a grep of
  `tools/freecad_object_smoke.py` on this branch for `probe` / `APART` /
  `App::Part` / `Recorder` returns nothing.

  This is not merely stale prose. Followed literally, the instruction pushes the
  sh-012 Implementer toward reinstating something the user deliberately removed
  during sh-011's sign-off, and the addendum recording that removal lives in
  sh-011's file, which the sh-012 Implementer has no reason to open. An sh-012
  Reviewer checking Must Have `:127` against the code finds a mismatch either
  way. sh-012 is `blocked_by: [sh-011]` and already sits at
  `current_phase: implementation`, so it dispatches as soon as this branch
  merges; there is no later moment that catches this.

  What is *not* broken, and should not be touched: the container-pattern
  decision. `:30-42` ("read the probe finding first") and Step 1 at `:298-300`
  route the Implementer to the `App::Part` / `Proxy.execute` section of
  `docs/freecadcmd-notes.md`, which is intact, unambiguous, and selects Pattern B
  (`docs/freecadcmd-notes.md:49-71`). That dependency holds; only the
  keep-the-probe instructions are stale.

  Fix: drop the probe from the "keep" lists at `:127` and `:302` so they name
  sh-011's checks and the marker. Consider the same one-word correction at `:272`
  ("anything about `App::Part` recompute ordering or child parenting that the
  probe did not already cover" → the recorded finding), which reads as a
  reference to a live artifact. As with F2, this is a mechanical text correction
  to sh-012's plan, not a re-plan: change nothing else in that file, and add
  nothing back to `tools/freecad_object_smoke.py`.

## Non-blocking notes

- **N4: nested backticks in the new addendum bullet render wrong**
  (`tasks/active/sh-011-freecad-object-layer.md:58-59`): the parenthetical
  ``(`## `App::Part` does not call a Python `Proxy.execute``)`` puts code spans
  inside a code span, so the markdown renders as a broken run of literal
  backticks rather than the section title. Quoting the heading as plain text
  (`the "App::Part does not call a Python Proxy.execute" section`) reads
  correctly. Fold into whatever round addresses F3.
