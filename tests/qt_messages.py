"""A Qt message handler for the offscreen GUI tests: it drops offscreen
Qt's unsupported-plugin warnings and forwards every other Qt message to
FreeCAD's console the way FreeCAD 1.1.3's own handler does.

Why the GUI tier needs the drop: ``tests/freecad_gui/conftest.py``.

Importable without FreeCAD, so the plain tier tests the handler with a
recording console.
"""

from collections.abc import Callable
from typing import Protocol

from PySide6 import QtCore

# QPlatformWindow's default implementations warn with this prefix. Only
# minimal platforms such as offscreen leave them unimplemented; xcb under
# Xvfb does not warn, so only the GUI tier installs the handler.
UNSUPPORTED_PLUGIN_PREFIX = "This plugin does not support "


class Console(Protocol):
    """The part of ``FreeCAD.Console`` the handler writes to."""

    def PrintLog(self, text: str, /) -> None: ...
    def PrintWarning(self, text: str, /) -> None: ...
    def PrintError(self, text: str, /) -> None: ...


MessageHandler = Callable[[QtCore.QtMsgType, QtCore.QMessageLogContext, str], None]


def forward(
    msg_type: QtCore.QtMsgType, category: str | None, text: str, console: Console
) -> None:
    """Write one Qt message to ``console``, or nothing when ``text`` starts
    with :data:`UNSUPPORTED_PLUGIN_PREFIX`.

    The written line is ``text`` plus a newline, prefixed by ``(category) ``
    when ``category`` is not ``None`` and not ``"default"``, an empty one
    included. Debug and info go to
    ``PrintLog``, warning to ``PrintWarning``, critical and fatal to
    ``PrintError``: a release build of FreeCAD 1.1.3's
    ``Gui::messageHandler``. It never aborts on a fatal message; Qt aborts
    once the handler returns.
    """
    if text.startswith(UNSUPPORTED_PLUGIN_PREFIX):
        return
    prefix = f"({category}) " if category is not None and category != "default" else ""
    line = f"{prefix}{text}\n"
    if msg_type == QtCore.QtMsgType.QtWarningMsg:
        console.PrintWarning(line)
    elif msg_type in (QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
        console.PrintError(line)
    else:
        console.PrintLog(line)


def message_handler(console: Console) -> MessageHandler:
    """A handler for ``QtCore.qInstallMessageHandler`` that applies
    :func:`forward` with ``console``."""

    def handle(
        msg_type: QtCore.QtMsgType, context: QtCore.QMessageLogContext, text: str
    ) -> None:
        # pyside6-stubs 6.7.3 leaves out the category attribute PySide6 has.
        category: str | None = context.category  # pyrefly: ignore[missing-attribute]
        forward(msg_type, category, text, console)

    return handle
