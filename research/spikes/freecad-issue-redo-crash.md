# Redo reads a freed view provider after Undo brings an object back

## Description

`Gui::Document::undo` and `Gui::Document::redo` both set
`d->_isTransacting`, and while it is set, `Gui::Document::slotNewObject`
appends every view provider it creates or reattaches to
`d->_redoViewProviders`. Only `Gui::Document::redo` walks that list and
clears it; `undo` leaves its entries behind.

So an Undo that brings an object back leaves the object's view provider in
the list. If a later Undo removes that object again, its view provider
moves into the step on the Redo list. A new change then drops the Redo
list, and `App::Transaction`'s destructor deletes the view provider, which
is still listed. The next Redo in the document calls `handleChildren3D` on
the freed pointer.

The code is the same on the 1.1.0 tag and on `main`.

## Steps to reproduce

Run this in the Python console of a fresh FreeCAD session:

```python
import FreeCAD
import FreeCADGui

doc = FreeCAD.newDocument("RedoCrash")
doc.UndoMode = 1


def step(name, action):
    doc.openTransaction(name)
    action()
    doc.commitTransaction()


step("Create", lambda: doc.addObject("Part::Box", "Box"))
step("Delete", lambda: doc.removeObject("Box"))
FreeCADGui.runCommand("Std_Undo")  # undoes Delete: Box is back
FreeCADGui.runCommand("Std_Undo")  # undoes Create: Box is gone again
step("Other", lambda: doc.addObject("Part::Box", "Other"))  # drops the Redo list
FreeCADGui.runCommand("Std_Undo")  # undoes Other, so there is something to redo
FreeCADGui.runCommand("Std_Redo")  # reads Box's freed view provider
```

Whether the last Redo crashes depends on whether the freed memory has been
reused. On Linux, starting FreeCAD with freed memory poisoned makes it crash
every time:

```sh
MALLOC_PERTURB_=165 GLIBC_TUNABLES=glibc.malloc.tcache_count=0 freecad
```

Without the `Other` step and its Undo, the same session survives the Redo.

## Expected behavior

Redo succeeds.

## Actual behavior

Segmentation fault:

```
Program received signal SIGSEGV, Segmentation fault.
#1  Gui::Document::handleChildren3D(Gui::ViewProvider*, bool) from libFreeCADGui.so+0x44
#2  Gui::Document::redo(int) from libFreeCADGui.so+0xbc
#3  Gui::View3DInventor::onMsg(char const*, char const**) from libFreeCADGui.so+0x54c
#4  Gui::Application::sendMsgToActiveView(char const*, char const**)
#5  Gui::Command::_invoke(int, bool)
```

Without poisoning, a longer session crashed the same way in an add-on's
automated GUI test, after undo and redo steps that delete and recreate
objects.

## Version

FreeCAD 1.1.3 from conda-forge, Linux aarch64 (Ubuntu, glibc 2.43), Python
3.12.14, Qt 6.11.2, Coin 4.0.10, under Xvfb. The code path is unchanged on
`main`.

## Possible fix

`Gui::Document::undo` could walk and clear `_redoViewProviders` the way
`redo` does, so no entry outlives the step that added it. Alternatively,
`Gui::Document::slotTransactionRemove` could erase the view provider it
hands to the transaction from the list.

An add-on can work around it for now: after a Gui Undo, run `Std_Redo`,
which empties the list while every entry is alive, then take that step back
with `App.Document.undo()`, which records no view providers.
