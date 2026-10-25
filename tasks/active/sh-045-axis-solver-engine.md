---
id: sh-045
title: "The constraint engine for one axis"
---

# sh-045: The constraint engine for one axis

## Summary
Adds the small solver M18 builds on. It is a self-contained module that takes
positions along one axis, the linear relations and lower bounds among them,
and drag targets. It moves the positions as little as possible from where
they are, and reports what is still free, which constraints conflict, and
which are redundant. Nothing calls it yet: sh-046 swaps the layout over to
it. It ships on its own so the numerical core gets a review of its own.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `freecad/Shelving/core/axis_solver.py` exists, imports only the
      standard library (nothing from `freecad.Shelving`), and defines no
      `Protocol`, ABC, or backend choice.
- [ ] Its suite, `freecad/Shelving/core/tests/test_axis_solver.py`, asserts:
      - consistent relations, no targets: every position comes back within
        1e-9 mm of its current value;
      - `x1 - x0 = 10` and `x1 - x0 = 12` together: a conflict naming both;
      - a consistent relation that the others already imply: solved, and
        reported redundant along with the relations it duplicates;
      - lower bounds that the relations cannot meet: a conflict naming
        those bounds and relations;
      - the freedom query names the relations that fix a determined
        difference of positions, and reports a free one as free;
      - a weighted target with no active bound lands within 0.001 mm;
      - a weighted target beyond what the bounds allow stops where the
        bounds hold it, with each bound it reached active;
      - a relation over three positions (`x0 + x2 - 2*x1 = 0`) solves, so
        relations are not limited to differences;
      - a system of 40 positions, each tied to its neighbor by a relation
        or a lower bound, with one target, solves.
- [ ] `grep -rn "axis_solver" freecad --include=*.py` names only
      `core/axis_solver.py` and its test.

## Advice
- **Interface:** one model axis per call, opaque. Inputs: named positions
  with current values; relations, each a general linear equality
  (coefficients over positions, a constant) with an id; lower bounds on a
  difference of two positions, each with an id; weighted targets on one
  position. Output: either the solved positions, a freedom query and the
  redundant relation ids, each with the ids it duplicates; or the
  conflicting relation and bound ids and the redundant ones. General
  linear, because M18's Equal and Even spacing are not differences. The
  caller names everything; the engine knows nothing of boards or regions.
- **Method:** bounded least squares with an active set, minimizing the sum
  of each position's squared motion from its current value (weight 1),
  plus each target weighted heavily enough to land within 0.001 mm.
  Consistent redundant equalities must solve rather than fail: a fully
  locked axis and documents that already hold redundant locks both produce
  them. A conflict names the smallest set the method finds, not
  necessarily a minimal one; say which in the docstring.
- **Freedom query:** given a linear expression over positions (a
  difference, in sh-046's use), says whether the relations and the active
  bounds determine it, and if so which relation and bound ids do.
  sh-046's `held_by` and reference-axis check are built on it.
- **Standard library only, pure Python, no numpy, no `Protocol` or
  swappable backend** (user decision). Systems are tens of positions, the
  core suite stays free of dependencies, and a second backend has no
  caller.
- **Speed:** sh-046 runs a solve on every pointer move of a drag, and the
  `large_unit` fixture (four columns of six openings) must keep up. Use
  exact elimination on the small dense system rather than iteration that
  converges slowly. Add no timing assertion, because it would be flaky.
- **Typed Python:** position ids are a `NewType` over `str`, constraint ids
  another; relations, bounds, targets and results are frozen dataclasses;
  signatures use `Mapping` and `Sequence`, never bare `dict` or `list`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's solver is the model:
  minimal motion from current geometry, a dragged point weighted to reach
  the pointer, and conflicting and redundant constraints reported
  separately. Its algorithms (DogLeg, Levenberg-Marquardt over nonlinear
  geometry) are heavier than linear constraints on one axis need.
- **Users never read the log:** the engine reports through return values;
  it writes no log text.
- **No manual QA case:** nothing user-facing changes.
- **Out of scope:** every caller. `core/solver.py` and `core/edit.py`
  change in sh-046.

## Plan
- [ ] **Step 1** (`core/axis_solver.py`): the types, the solve, the
      freedom query, and conflict and redundancy reporting, per Advice.
- [ ] **Step 2** (`core/tests/test_axis_solver.py`): the suite named in
      the Must Have.
- [ ] **Step 3** (`.claude/docs/code-map.md`): name the engine in the
      `core/` entry.

## Review log
