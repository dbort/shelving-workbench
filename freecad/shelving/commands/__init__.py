"""GUI commands for the Shelving Workbench.

Each module here defines one `Gui.Command` class and registers it with a
headless-safe `Gui.addCommand` guard, so importing the package under
``freecadcmd`` (no GUI) does not raise. `init_gui.Initialize` imports these
modules and wires their command ids into the toolbar and menu.
"""
