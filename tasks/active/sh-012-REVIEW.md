# sh-012 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green end to end on `sh-012` (146 pytest cases, mypy clean
over 37 files, both `freecadcmd` smokes reporting their markers, exit 0). The
over-constraint case's stderr `RuntimeError` traceback is the expected
error-path shape, not a failure. The container split, the driver, the command,
the toolbar wiring, and both docs changes all match the plan. Two test-strength
gaps block approval; both are edits to `tools/freecad_object_smoke.py` and
neither needs a change to the shipped code.

## Blocking findings

- **F1: the over-constraint case's error assertion is satisfied by a non-error
  state** (`tools/freecad_object_smoke.py:161`, asserted at
  `tools/freecad_object_smoke.py:257`): `_in_error_state` returns `"Touched" in
  driver.State or not driver.isValid()`. `"Touched"` is not an error condition.
  Line 252 assigns `driver.Layout = bad_layout` immediately before the
  recompute, which touches the driver, so a driver the recompute never visited
  carries `"Touched"` just as an errored one does. The `or` short-circuits on
  that first disjunct, so a passing run establishes nothing about `isValid()`.
  The two assertions that follow are vacuous under the same hypothesis: the
  plank count at line 258 and the `Layout` string at line 259 are both
  unchanged-by-construction if `execute` never ran. "The object was not in the
  document's work list" is not a hypothetical failure mode in this codebase; it
  is the exact one the driver already works around for its plank children
  (`freecad/shelving/objects/shelving_unit.py:208`). The Must Have names three
  acceptable predicates — `"Error" in unit.State`, `unit.isValid() is False`, or
  the recompute raised — and `"Touched" in State` is none of them. Drop the
  `"Touched"` disjunct so the assertion rests on the error state itself. If
  `isValid()` alone turns out not to hold under `freecadcmd`, assert on the
  raised exception instead (lines 253-256 currently swallow it, so the third
  permitted predicate is available but unused) or on `"Invalid" in
  driver.State`, and record which signal FreeCAD 1.0 actually reports for a
  proxy-`execute` failure in `docs/freecadcmd-notes.md` so the next scripted
  object does not have to rediscover it.

- **F2: the reconciliation's remove branch has no automated coverage**
  (`freecad/shelving/objects/shelving_unit.py:204`): removing a plank whose
  `NodeId` has left the spec set is a Must Have behavior of the reconciliation
  ("After the walk, remove every plank child whose `NodeId` is not in the new
  spec id set"), and `_check_unit_end_to_end` never exercises it — the sequence
  is create 4 planks, widen, relayout up to 6 planks, over-constrain with the
  count unchanged. The child count never goes down, so `doc.removeObject` is
  dead code as far as the checks are concerned. It is also the riskiest line in
  the module: deleting a `DocumentObject` from inside another object's `execute`
  mid-recompute is the same class of FreeCAD work-list hazard that already
  forced the explicit per-child `recompute()` at line 208, and nothing in the
  branch demonstrates it behaves. Add a step to `_check_unit_end_to_end` that
  writes a single-`Leaf` `Carcass` (reusing `carcass_id`) back into
  `driver.Layout`, recomputes, and asserts the plank count is back to 4, that
  neither shelf `NodeId` survives in the document, and that the four shell
  planks kept their `Name`s (proving the reconciliation removed only the
  shelves rather than rebuilding the shell).

## Non-blocking notes

- **N1: the top-level `shelving_core` import is accepted; do not revert it and
  do not re-litigate it** (`freecad/shelving/objects/shelving_unit.py:407-417`
  of the diff, the comment block above the imports). The deviation from
  `## Frontier Advice`'s "import from `freecad.shelving.vendor.shelving_core.*`"
  line is correct and the reasoning checks out: `shelving_core/expand.py:18` and
  `shelving_core/solver.py:19` bind their layout classes with a bare `from
  shelving_core.layout import ...`, `tools/vendor-core.sh` copies them
  byte-identically, and `shelving_core/expand.py:133` guards the divider walk
  with `if not isinstance(bay, Split): return` — a silent early return, not a
  raise. A carcass built from the vendored `layout` module therefore loses every
  divider with no error. No all-vendored import combination avoids this, because
  the vendored `expand` resolves `Split` to the top-level package regardless of
  the path its caller used. The Implementation note, the friction-log entry, and
  the in-file comment together are adequate documentation. The `[~]` marker on
  the affected Must Have bullet is the right treatment.

- **N2: the vendored copy is not self-contained, and that is pre-existing, not
  sh-012's to fix** (`freecad/shelving/vendor/shelving_core/layout.py:22`,
  `.../expand.py:18-20`, `.../solver.py:19-30`). Because those intra-package
  imports use the bare distribution name, importing
  `freecad.shelving.vendor.shelving_core` at all requires a top-level
  `shelving_core` on `sys.path`; under a real Addon Manager install there is
  none, so the vendored copy would `ImportError` on its own even before
  `shelving_unit.py`'s import path enters the picture. sh-012's `## Scope guard`
  forbids touching `shelving_core/`, the vendored copy, and `vendor-core.sh`, so
  the Implementer could not have fixed it here, and M3 is explicitly a
  headless/dev milestone with no real-install check. Deferring to the friction
  log is the right call. The friction entry already names the two candidate
  fixes (relative imports upstream, or an import rewrite in `vendor-core.sh`);
  this wants its own task before the first packaged install, and that task
  should add a check that imports the vendored package with the repo root off
  `sys.path`.

- **N3: the per-child `obj.recompute()` is sound and is not masking an ordering
  bug** (`freecad/shelving/objects/shelving_unit.py:208`). Planks carry no
  `App::PropertyLink` back to the driver, and `App::Part` containment is not a
  recompute dependency, so the document's DAG imposes no driver-before-plank
  ordering to get wrong; a plank created during the driver's own `execute` is
  not in the in-flight work list at all. The explicit recompute substitutes for
  an absent dependency edge rather than papering over a mis-ordered one, and the
  `touch()` before it on the update path is what keeps the recompute from being
  skipped as clean. Re-recomputing a plank the document would also have visited
  is harmless. Keep it. If a later milestone gives planks a real link to the
  driver, revisit.

- **N4: `Carcass.from_json` failures are not wrapped**
  (`freecad/shelving/objects/shelving_unit.py:127`). The `try` only covers
  `expand`, so a malformed hand-edited `Layout` surfaces a raw
  `json.JSONDecodeError` / `KeyError` instead of the `RuntimeError` the rest of
  the error path uses. The Must Have only specifies the wrap for `expand`, and
  FreeCAD marks the object errored either way, so this is not blocking — but
  `docs/manual-qa.md` case 5 puts a human into exactly this position, and a
  message shaped like the solver's would read better in the report view.

- **N5: `driver.Width = 900` is load-bearing but unexplained**
  (`tools/freecad_object_smoke.py:208`). It resets the width the previous block
  left at 1000 so the promoted-property override does not contradict the
  relayout carcass and break the `900 - 2t` shelf-size assertion at line 229.
  The comment above it explains only the `carcass_id` reuse. One clause on the
  reset would save the next reader the trace.

- **N6: the smoke now holds two class identities of the core**
  (`tools/freecad_object_smoke.py:34-43` of the diff): it builds carcasses from
  `freecad.shelving.vendor.shelving_core.*` while `shelving_unit` works in
  top-level `shelving_core.*`. It is safe today because every carcass crosses to
  the driver as JSON, which launders the identity. It stops being safe the
  moment an assertion compares a core object or enum member across the two. A
  one-line comment at the vendored import block saying the JSON round-trip is
  what makes the mix safe would fence it off until N2 is fixed.
