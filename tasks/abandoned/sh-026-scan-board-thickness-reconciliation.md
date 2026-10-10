---
id: sh-026
title: "Reconcile a board's catalog-resolved thickness with its raw measured width"
---

# sh-026: Reconcile a board's catalog-resolved thickness with its raw measured width

## Summary
Would have made scanning reconcile each board's catalog thickness with its
measured width, so a run whose only other members are fixed-size openings
still adds up exactly instead of refusing to solve.

## Abandoned

Abandoned on 2026-10-09 at the user's decision. sh-030 removes the material
catalog, and a board's thickness becomes its own slot width in the scan
grid, measured from the same coordinates as its siblings, so the mismatch
this task reconciled no longer exists. Four rounds of work in progress on
the `sh-026` branch had narrowed the fix to runs with a direct `Bay`
sibling; that branch was deleted unmerged, its last commit being `3f14505`.
The approved plan is in git history at
`tasks/active/sh-026-scan-board-thickness-reconciliation.md`.

Superseded by: sh-030.
