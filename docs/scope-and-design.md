# Scope and design

What this workbench is for, what it deliberately is not for, and how it is
built. This is the design of record. It supersedes
[`architecture.md`](architecture.md), which describes an earlier design
that is still what the code implements; [`roadmap.md`](roadmap.md) tracks
the milestones, and
[`parametric-model-evaluation.md`](parametric-model-evaluation.md) carries
the evidence and the reasoning behind the decisions stated here.

## Summary

A FreeCAD workbench for designing shelving, built so that the geometry it
produces belongs to your document rather than to the workbench.

A shelving unit is designed as a flat front elevation: a rectangle divided
into compartments by shelves and dividers, each panel with a real
thickness taken from a material list. Change the height and the shelves
redistribute. Type an exact opening and its neighbours absorb the
difference.

What makes it unusual is the other direction. The panels are ordinary
FreeCAD solids with no hidden machinery attached, so any other tool can
read, measure, cut, and export them, and a document opens correctly on a
machine where this workbench is not installed. The workbench can also read
an arrangement of panels back and recover the layout from it, which means
it works on shelving you have already modelled, and it means editing a
panel with somebody else's tool is a supported thing to do rather than
something that breaks the model.

## Background

FreeCAD already covers most of this ground in pieces.

**Part and PartDesign** model solids well and know nothing about
furniture. Nothing stops you drawing a bookcase as twelve boxes, and
people do. What you lose is any notion of a shelf, an opening, or a rule
about how space is shared, so changing the height means moving every shelf
by hand.

**Arch and BIM** work at building scale with walls, windows and levels.
The abstractions are the wrong size for a bookcase and the wrong shape for
a cut list.

**Assembly** positions finished parts relative to each other. It solves
where things go, not what they are.

**The Woodworking workbench** by dprojects is the closest neighbour and
the most important one. It is a large, mature, MIT-licensed collection of
tools for exactly this domain: it generates cabinet carcasses from
dimensions, moves and resizes panels, drills dowel and shelf-pin holes,
applies edge banding, produces cut lists grouped by container, and exports
to spreadsheets. Its panels are plain FreeCAD solids, usually boxes, held
in ordinary containers, and its tools write plain values rather than
expressions.

Two things about it shape this project. The first is that its substrate is
the right one: plain axis-aligned solids, with dimensions read directly off
the object, are readable by everything and outlive any particular add-on.
This workbench adopts the same conventions deliberately, so that its output
is Woodworking's input and the reverse.

The second is what it does not do. Woodworking's tools are stateless
operations on the current selection. No tool looks at an arrangement of
panels and works out that it is three compartments separated by two
shelves. There is no model of an opening, no notion that one dimension
drives another, and so no reflow: resizing a carcass does not move the
shelves inside it. Its cabinet generator produces a finished arrangement
from a dialog, and from then on the panels are just panels.

So the landscape splits cleanly. Tools that keep a model of furniture own
their objects, and the document depends on them. Tools that leave the
geometry native keep no model, and nothing redistributes.

## The problems this project takes on

Four, in order of how much they distinguish it.

**Keeping a layout model without owning the geometry.** A design has
intent that its geometry cannot express. A 300 mm compartment looks
identical whether it was set to 300 mm deliberately or came out at 300 mm
because it shares the leftover space with three others. Resize the unit
and those two behave completely differently. The intent has to live
somewhere, and the usual answer is for the tool to own the objects, which
is what makes the document depend on the tool. The problem is to keep
enough intent to reflow while leaving every panel a plain solid that
anything can read.

**Recovering structure from an arrangement.** Given a set of panels, work
out that they form a unit with a particular arrangement of compartments,
which panel runs through at each joint, and which spaces are inside the
unit rather than outside its outline. This is what makes the workbench
usable on geometry it did not create, whether that came from another tool,
from an earlier project, or from somebody drawing boxes. It is also what
makes hand-editing safe, because the workbench can always re-read the
truth off the geometry instead of insisting on its own copy.

**Handling the shapes real projects actually have.** A closed rectangular
box is the easy case and not a very common one. Real units step at the top
or the bottom, mix panel depths in one carcass, sit in pairs whose sides
meet, have panels notched to clear something in the wall, and hold a shelf
that is a different material from its neighbours. A model that only
expresses the easy case forces every real design out of it immediately.

**Connecting a design to what surrounds it.** A unit is built for a
particular alcove, and the alcove's dimensions should be able to drive it.
The other direction matters too: a countertop, a drawing, or a cut list
should be able to read the unit's real dimensions. Neither should require
the reader to understand anything about this workbench.

The first two are the ones nothing else does. The last two are the reason
the first two are worth doing.

## Deliberately out of scope

Some of these are permanent, and some are simply not near-term. Both kinds
are listed so the edges are visible.

**Fabrication.** Kerf, sheet layout and nesting, cost rollups, hardware,
fasteners, edge banding, line boring, and dowel and pocket holes are
downstream of the shape this workbench describes. Woodworking covers much
of this well and operates on the same solids, so the answer is to hand off
rather than to duplicate.

**Doors, drawers, and face frames** as modelled things with their own
behaviour. A door is a panel like any other and can be drawn as one; it
just is not something the layout understands.

**Panels that are not rectangular boxes.** An L-shaped top cut from one
sheet, a mitred corner, a shelf notched around a post, and a panel scribed
to an out-of-square wall have no representation. A panel like that can be
carried along and positioned, but the workbench will not generate or
reshape it. This is the sharpest edge of the whole design and the one most
likely to be met in practice.

**Anything not axis-aligned.** A cabinet set at forty-five degrees across
a corner is a normal thing to build and is outside this model entirely.

**Layouts that are not made by straight cuts.** Four dividers arranged in
a pinwheel, each stopping against the next, is a real thing to build and
has no representation as a nested arrangement. It is refused rather than
approximated.

**Assemblies spanning more than one plane**, meaning shelving set into a
corner, a T of runs, or two runs facing each other across an aisle. This
one is not permanent. The model is being built so that it does not have to
change to accommodate them later, but neither the editor nor the reader
handles them now, and an attempt is refused.

**Structural analysis, rendering, and drawing production** beyond what
FreeCAD already provides for ordinary solids.

**Replacing Woodworking.** The goal is to be worth installing alongside
it.

## How it is used

Two ways in, and they meet in the same place.

**Adopting what you already have.** You have a unit modelled as panels,
whether you drew them, generated them with another tool, or inherited the
file. You select the container holding them and ask the workbench to read
it. It works out the arrangement and tells you what it found, including
anything it could not read. From there it is an ordinary editable unit.

If it cannot read the arrangement, it says which panels defeated it and
why. It never guesses, and it never quietly produces a plausible answer to
a question it could not actually resolve.

**Starting from nothing.** You create a unit, give it overall dimensions
and a material, and get a plain carcass. Editing proceeds identically from
there.

**Editing.** A unit opens as a front elevation. You pick a compartment and
split it, drag a shelf, or type an exact opening size. Everything else
redistributes according to what is fixed and what is free, and the 3D
follows. Setting an exact size makes that opening fixed, and its
neighbours take up the difference. An arrangement that cannot be satisfied
is an error with an explanation, not a silently wrong result.

**Editing outside the workbench.** You move or resize a panel with any
tool you like, then ask the workbench to take the change up. It re-reads
the geometry, treats what you changed as the thing you meant, and reflows
the rest around it. This is the same operation as adopting a unit for the
first time, so there is no separate mode to be in and nothing to break by
touching a panel directly.

**Driving from its surroundings.** A unit's overall dimensions can be
bound to something else in the document, so an alcove drives the carcass.
Named values can be shared, so several units keep the same shelf spacing.

**Handing off.** Everything the workbench produces is a plain solid, so
another tool's cut list, drilling, or export runs on it without
translation. Uninstalling the workbench leaves the document complete.

# Design

The rest of this document describes how the above is delivered, in broad
strokes. It states what each part takes in, what it produces, and what it
refuses. It does not describe algorithms.

## The layout model

The model describes one unit as a rectangle divided by straight cuts.

A **region** is a rectangular area of the elevation. It is one of three
things: an open compartment, a void meaning space inside the unit's
bounding rectangle that is not part of the unit, or a division. A
**division** cuts a region along one axis into an ordered run of **items**,
each item being either a panel or another region. Items run in order along
the axis and need not alternate, so two adjacent panels are two boards face
to face.

Each item contributes a size along the division's axis. A panel
contributes its material thickness. A region contributes a **rule**: a
fixed size, a share of what is left, or an equal share. Fixed sizes drive
the layout, shares absorb what is left over, and a division whose fixed
sizes exceed the space available, or which has slack and nothing to absorb
it, is an error naming the region responsible.

Three consequences are worth stating because they are what the model buys.

There is **no separate concept of a carcass shell**. The outer panels of a
unit are simply the outermost items of its outermost divisions. A unit
whose top runs the full width and a unit whose sides run full height
differ only in the order the cuts nest, and both are ordinary. This
matters because generated cabinets in the wild use both, sometimes from
the same tool.

**Which panel runs through a joint is the nesting order**, not a separate
setting. The panel cut first runs through; panels in the pieces it creates
stop against it.

**An outline that steps** is expressed with voids. A column that is
shorter than its neighbour is a region holding a compartment, its own top,
and a void taking the remaining height. No rule about outlines is needed.

The model's restrictions are that every member is a rectangular box, every
cut is axis-aligned, a unit occupies one elevation plane, and a layout
must be reachable by straight cuts.

## Reading geometry

**Input** is a container of solids. **Output** is a layout tree, or a
refusal that names the objects responsible.

The reader works out which axis is the depth, treats the other two as the
elevation, and divides the elevation wherever a straight line passes
without cutting through any panel. Where two lines are closer together
than a joint tolerance they are one joint rather than a compartment, which
is what keeps a shelf held a millimetre off each side from producing two
one-millimetre compartments. Space that connects to the outside of the
bounding rectangle is a void; space enclosed by panels is a compartment.

Its guarantee is that it does not guess. Every arrangement it cannot
express is refused with the offending objects named, and every object it
could not read is reported. That second point matters more than it
sounds: a missing panel does not cause a failure, it causes a plausible
and wrong answer, because compartments that were enclosed read as open
instead.

Three things geometry cannot tell it, all of which are supplied rather
than inferred:

- **Rules**, because a compartment that is fixed and one that happens to
  have solved to the same size are identical. Stored intent wins; without
  it, equal neighbours are treated as sharing and unequal ones as fixed.
- **Material identity**, because thickness alone does not name a stock
  entry.
- **Which side the unit faces**, which decides nothing about the geometry
  and everything about which end is called the left. Two weak hints exist,
  a back or a front panel, and a front inset with a flush rear, and both
  fire rarely. Unknown is the normal answer, it is stored once and
  remembered, and a guess is labelled as one.

Parts that are not simple boxes are read by their overall size and marked
as unchangeable, so a panel notched to clear something in the wall takes
part in the layout without the workbench trying to regenerate it. Its size
then drives the space around it instead of being driven by it.

## Writing geometry

**Input** is a layout tree and a container. **Output** is plain solids in
that container: matched ones updated where they stand, new ones created,
removed ones deleted.

Matching is by the object's own identity, so a panel you renamed, coloured,
or referenced from elsewhere in the document survives a reflow. Nothing is
recreated that did not need to be. Panels marked unchangeable may be moved
but are never rewritten.

## What is stored, and where

The principle is that anything derivable from geometry is derived, because
every stored value is a value that a copied object can carry incorrectly.

**Identity is FreeCAD's own object name.** It is never stored as a
property, which means it cannot be copied: duplicating a panel produces a
distinct object by construction rather than a conflict to resolve. Two
provenance values recorded when a panel is first tagged, its name and its
document, classify what a mismatch means later. A changed name is a copy,
and the answer is to treat it as new geometry, which is what somebody
copying a shelf to make another shelf wanted. A preserved name in a
different document is a relocation.

**On each panel**: its material, and the rule for the space beside it.
Nothing else. What kind of panel it is and how far it is held off its
neighbours are both derived.

**On the container**: the unit's identity, its elevation plane, which way
it faces, and a record of the compartment rules. That record is not the
source of truth for anything geometric; positions always come from the
solids, and a record that is missing or stale falls back to inference.

Named values that several places share, such as a shelf spacing used by
more than one unit, live in an ordinary FreeCAD variable set, which means
they can carry expressions and be driven from elsewhere in the document
with no help from this workbench.

## What you see in the tree

Everything is a stock FreeCAD object.

```
Bookcase                        App::Part
  Bottom                        Part::Box
  Left Side                     Part::Box
  Right Side                    Part::Box
  Shelf 1                       Part::Box
  Shelf 2                       Part::Box
Shelving Materials              a material list
Shelving Parameters             App::VarSet, when named values are used
```

The unit is a stock container, either a `Part` or a link group, chosen by
you rather than created behind your back; it is what gives the unit a
single position and what makes it work with links and assemblies. Reading
a container is how the workbench knows which panels form one unit, which
also means you decide whether two units that touch are one thing or two,
since nothing in their geometry can say.

Each panel is a `Part::Box` with a readable label. Selecting one shows its
dimensions where they always are. The extra values the workbench keeps
appear in their own property group, mostly read-only, and none of them are
needed to draw the object.

No object in the tree carries workbench code. That is what makes a
document open correctly without this add-on installed: the panels are
still panels, still the right size, still where they were.

## Coexisting with other workbenches

The output follows the conventions already used by the tools most likely
to read it: axis-aligned boxes whose length, width and height lie along X,
Y and Z, held in ordinary containers. Woodworking's cut list, drilling,
edge banding, and export tools work on a finished unit with no
translation, and panels made with its tools can be read back.

Three rules keep that true.

**Nothing is taken over.** No panel carries a proxy or a dependency on
this workbench, so no other tool has to understand anything to operate on
one.

**Nothing is quietly reshaped.** A part the workbench did not create and
cannot regenerate is carried, positioned, and left alone.

**Refusal over approximation.** An arrangement outside the model is
reported with the objects named. The failure mode worth avoiding is not a
refused unit, it is a unit that reads successfully and describes something
that is not there.

## Known gaps

Stated because they are the places the design is currently thin.

Whether a panel actually reaches its neighbours is not checked. A shelf
floating clear of both sides is a valid arrangement of straight cuts, so
it is accepted, and the gaps beside it are reported as compartments.
Whether a design is buildable is a separate question from whether it is
expressible, and only the second is asked.

Compartments in different units do not line up unless their rules happen
to agree. Making a shelf carry across from one unit to the next needs
shared named values, which the model has a place for but does not yet use.

Assemblies on more than one plane are refused rather than supported, and
the editor works on one unit at a time.
