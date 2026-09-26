"""The elevation editor: Qt scene rendering, the edit session, and the panel.

``scene.py`` is tested under plain pytest with an offscreen ``QApplication``
and ``session.py`` under ``freecadcmd``, so both run headlessly.
``FreeCADGui.Control``, the task-panel shell, does not exist under
``freecadcmd``, so ``panel.py`` is checked only by hand. Keep every decision
worth testing out of ``panel.py``.
"""
