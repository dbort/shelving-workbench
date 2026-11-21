"""GUI commands for the Shelving Workbench.

Each module here registers its commands with a headless-safe
`Gui.addCommand` guard, so importing the package under ``freecadcmd`` (no
GUI) does not raise. `init_gui.Initialize` imports these modules and wires
their command ids into the toolbar and menu.
"""
