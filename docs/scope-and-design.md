# Scope and design

A FreeCAD workbench for designing shelving, built so that the geometry it
produces belongs to your document rather than to the workbench.

A unit is designed as a flat front elevation: a rectangle divided into
compartments by panels of real thickness. Change the height and the
shelves redistribute; type an exact opening and its neighbors absorb the
difference. The panels are ordinary FreeCAD solids with nothing hidden
attached, so any tool can read, cut and export them, and a document opens
intact where this workbench is not installed. The workbench can also read
an arrangement of panels back and recover its layout. That makes it work
on shelving modeled elsewhere, and it makes editing a panel with another
tool a supported operation.

## Why it exists

Part and PartDesign model solids but know nothing about a shelf or an
opening, so resizing a bookcase means moving every shelf by hand. Arch and
BIM work at building scale. Assembly positions finished parts.

The Woodworking workbench (dprojects, MIT) is the closest neighbor. Its
panels are plain axis-aligned boxes in ordinary containers, and its tools
write plain values: a substrate everything can read. This workbench adopts
the same conventions, so each one's output is the other's input. What
Woodworking lacks is a model: its tools are stateless operations on a
selection, so nothing knows that two shelves divide three compartments,
and resizing a carcass moves nothing inside it.

Tools that model furniture own their objects, and the document depends on
them. Tools that leave geometry native keep no model. This project keeps
enough layout intent to reflow while every panel stays a plain solid, and
recovers that intent from geometry it did not create. It is meant to be
installed alongside Woodworking. Contributing it upstream does not fit:
Woodworking is a single-author toolbox of stateless operations, and a
modal layout editor is the kind of interface change its contribution terms
exclude.

## Out of scope

- **Fabrication**: kerf, nesting, cost, hardware, edge banding, boring and
  joinery holes. Woodworking does these on the same solids.
- **Doors, drawers and face frames** as things with behavior. A door can be
  drawn as a panel.
- **Non-rectangular panels**: an L-shaped top, a miter, a notch, a scribe.
  Such a part is carried and positioned but never generated or reshaped.
  This is the edge users are most likely to meet.
- **Anything not axis-aligned**, such as a 45-degree corner cabinet.
- **Layouts not made by straight cuts**, such as a pinwheel of four
  dividers each stopping against the next. Refused, never approximated.
- **More than one elevation plane** (a corner, a T, an aisle). Refused for
  now; the model is built so it need not change to allow them later.
- **Structural analysis, rendering, and drawings** beyond what FreeCAD
  offers for any solid.

## The layout model

A **region** is a bay (an open compartment), a void (space inside the
bounding box that is not part of the unit), or a division. A **division**
cuts a region along one axis into an ordered run of items, each a board or
a sub-region; two adjacent boards are two boards face to face.

A board contributes its thickness along the run. A region contributes a
rule: a fixed size, or a share of what is left. Fixed sizes drive, shares
absorb, and a run whose fixed sizes overflow, or that has slack and nothing
to absorb it, is an error naming the region. The user sees a fixed region
as locked and a sharing one as unlocked. Locking or unlocking moves
nothing, and the editor keeps one unlocked region in every run so a change
to the unit's size has somewhere to go.

A drag moves a board and every board joined to it through locked regions;
only the first unlocked region on each side changes size. A board with
only locked regions between it and the end of its run is held until one
is unlocked. A drag past the end of its travel stops the board there
without a message, the way a scroll bar's thumb stops at the end of its
track, leaving the shrinking region 5 mm: a narrower opening would vanish
the next time the unit is read back from its boards.

A fixed size measures the clear opening, or includes the next board, which
is how a shelf spacing quoted top face to top face is given. The two place
boards identically and diverge only when a thickness changes: a clear size
holds the opening, an inclusive size holds the shelves.

What the model buys:

- **No carcass shell.** The outer boards are the outermost items of the
  outermost divisions, so full-width tops and full-height sides are both
  ordinary.
- **Which board runs through a joint is the nesting order.** The board cut
  first runs through.
- **A stepped outline is voids.** A short column is a region holding a bay,
  its own top, and a void.

## Reading geometry

**In:** a container of solids. **Out:** a region tree, or a refusal naming
the objects responsible.

The reader takes the shallowest axis as depth, then divides the elevation
wherever a line crosses no board. Lines closer than the joint clearance
are one joint, so a shelf held a millimeter off each side does not create
two one-millimeter compartments. Space connected to the outside of the
bounding box is a void; enclosed space is a bay.

A unit's position comes from its boards, as its size does: the two are the
bounding box, in the container's coordinates, of the boards the tree
places. A back or front panel set aside, an unreadable part, or an object
left alone counts toward neither. A resize keeps that box's minimum corner
where it is and grows the unit on its far sides, the way a `Part::Box`
grows from its `Placement`, so a unit built anywhere in its container
stays there through every edit.

It never guesses. Every arrangement it cannot express is refused with the
objects named, and every object it cannot read is reported, because a
silently dropped panel turns enclosed bays into open ones and yields a
plausible, wrong tree.

Geometry cannot say two things, so both are stored once set:

- **Lock and basis.** A fixed 300 mm opening and a share that solved to
  300 mm look identical, as do a clear size and a spacing. Without stored
  intent, every bay shares leftover space in proportion to its size, and a
  void keeps its size unless nothing beside it can change. Sizes always
  come from the boards, so a board moved by hand stays where it was moved;
  the record keeps only whether each region is locked and what its size
  measures.
- **Facing**: which end of the depth axis is the front, which decides what
  is called left. Two hints exist (a back or front panel, an inset front
  with a flush rear) and both fire rarely. Unknown is the normal state,
  and a guess is labeled as one.

A part that is not a simple box is read by its bounding box and pinned: it
takes part in the layout, its size drives the space around it, and it is
never regenerated.

A panel thin through the depth stays out of the tree. Once the facing is
known, a panel set within the carcass's depth, or proud behind it and under
half the stock's thickness, is the unit's back. That is the same reading
the facing hint takes, so the panel that settles the facing and the panel
that follows as the back never disagree, and with the facing unknown no
panel is a back. A stock-thick panel proud of the front reads as a door and
stays where it is: a door belongs to one opening, and following the unit's
outline would misplace it after a split.

At every read, each of a back's four edges is matched to the board face it
lies on, as a Part attachment follows its support's face. A face across a
board's thickness, such as the floor's underside, wins over a board's end
at the same place. An edge on no board face follows the unit's outer face
on its side at the distance it has from it, and so does an edge whose board
an edit removes, until the next read matches it afresh. Through the depth a
back keeps its thickness and its distance from the carcass's rear face.
Nothing about a back is stored, so a back moved by hand is followed from
where it now is, and the unit's size still measures the carcass alone.

## Writing geometry

**In:** a region tree and a container. **Out:** plain `Part::Box` solids
in that container: matched ones updated in place, new ones created,
removed ones deleted. A write deletes only objects this workbench tagged;
the editor deletes any other object only when you select it for deletion.
A pinned part may move but is never rewritten. A back is moved and resized
onto the faces it follows, and only moved when it is not a plain box, but
it is never tagged or deleted; an edit that would leave it no width or
height is refused.

## Editing

Edit Unit works in FreeCAD's 3D view, the way the Sketcher's edit mode
does: the camera turns to face the unit's front, FreeCAD's own navigation
stays as it is, and on Close the camera returns when the Sketcher's
"Restore camera position after editing" preference asks it to. The
openings and their dimensions are drawn over the real boards, on whichever
face the camera sees. A click on a board selects the whole board through
FreeCAD's own selection; a click on a dimension types its size on the spot;
buttons over a selected opening add a shelf or a divider; an arrow drags
the selected board; Delete removes it. The task panel holds only what has
no place on the drawing: the unit's size, what a selected opening's size
measures, and the objects the workbench did not create, each saying
whether it follows the boards as a back or is left alone.

Each opening's dimension carries a padlock just past its text, closed for a
locked opening and open for an unlocked one, in the dimension's own color.
Clicking it locks or unlocks the opening, and typing a size locks it. An
unlocked opening alone in its run shows no padlock, since it can never
lock. A selected board held in place shows a closed padlock where its arrow
would be and outlines the locked openings holding it; clicking that padlock
unlocks them, and the arrow takes its place. The padlock is the only way to
unlock: the shares behind unlocked openings never appear in the interface.

The unit's container cannot enter FreeCAD's edit mode without workbench
state in the document, so the editor adds its drawing and input handling
to the view when it opens and takes every one of them away when it closes.
Each edit is its own undo step, and FreeCAD's Undo and Redo work during
the edit as they do anywhere else.

Matching is by object identity, so a renamed, recolored or referenced
panel survives a reflow. Material, color and grain live where Woodworking
keeps them (`ShapeMaterial`, the view's appearance, a per-face `Grain`
list), and a reflow never writes them. A new panel copies them, and its
thickness, from a source board lying the same way: a shelf in the same
opening, then the nearest such shelf, then the nearest outer panel, then
the nearest panel of any kind. A stock swap changes the thickness, the
`ShapeMaterial` or the color of the selected panels together, as one undo
step, and never their grain.

## What is stored

Anything derivable from geometry is derived, because every stored value is
one a copied object can carry wrongly.

- **Identity** is FreeCAD's object `Name`, never stored as a property, so a
  copy is a distinct object by construction. Provenance recorded at
  tagging (the `Name` and the document `Uid`) classifies a mismatch: a
  changed `Name` is a copy and is adopted as new geometry; a kept `Name` in
  another document is a relocation.
- **On the container:** the unit's id, depth axis, facing, and a record of
  region rules keyed by their bounding boards. Positions always come from
  the solids, the unit's own size and position included; a missing or
  stale record falls back to inference.
- **Named values** shared between units will live in an ordinary
  `VarSet`.

The tree holds only stock objects:

```
Bookcase                        App::Part (or a link group)
  Bottom                        Part::Box
  Left Side                     Part::Box
  Shelf 1                       Part::Box
```

You choose the container, and with it whether two touching units are one
unit or two, which their geometry cannot say. No object carries workbench
code, so the panels are still panels, the right size, where they were,
with the workbench uninstalled.
