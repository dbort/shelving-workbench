"""The elevation editor: Qt scene rendering, the edit session, and the panel.

``scene.py`` builds and hit-tests a ``QGraphicsScene`` from a ``Unit`` and its
solved spaces; ``session.py`` owns the document, the transaction, and the
write path for one editing session; ``panel.py`` is the Qt dialog that wires
buttons to a session. See this repo's ``sh-020`` task file for why the split
between the three is load-bearing.
"""
