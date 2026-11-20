"""Unit tests for tests.qt_messages, with a recording console in place of
FreeCAD's."""

from dataclasses import dataclass, field

import pytest
from PySide6 import QtCore

from tests.qt_messages import forward, message_handler

_Msg = QtCore.QtMsgType


@dataclass
class _Console:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def PrintLog(self, text: str, /) -> None:
        self.calls.append(("PrintLog", text))

    def PrintWarning(self, text: str, /) -> None:
        self.calls.append(("PrintWarning", text))

    def PrintError(self, text: str, /) -> None:
        self.calls.append(("PrintError", text))


@pytest.mark.parametrize(
    "text",
    [
        "This plugin does not support raise()",
        "This plugin does not support propagateSizeHints()",
    ],
)
def test_offscreen_plugin_warnings_are_dropped(text: str) -> None:
    console = _Console()
    forward(_Msg.QtWarningMsg, "default", text, console)
    assert console.calls == []


@pytest.mark.parametrize(
    "text", ["probe", "QWidget::repaint: Recursive repaint detected"]
)
def test_other_warnings_are_forwarded(text: str) -> None:
    console = _Console()
    forward(_Msg.QtWarningMsg, "default", text, console)
    assert console.calls == [("PrintWarning", f"{text}\n")]


@pytest.mark.parametrize(
    ("msg_type", "method"),
    [
        (_Msg.QtWarningMsg, "PrintWarning"),
        (_Msg.QtCriticalMsg, "PrintError"),
        (_Msg.QtFatalMsg, "PrintError"),
        (_Msg.QtInfoMsg, "PrintLog"),
        (_Msg.QtDebugMsg, "PrintLog"),
    ],
)
def test_each_message_type_reaches_freecads_level(
    msg_type: QtCore.QtMsgType, method: str
) -> None:
    console = _Console()
    forward(msg_type, "default", "text", console)
    assert console.calls == [(method, "text\n")]


@pytest.mark.parametrize(
    ("category", "line"),
    [
        ("qt.qpa.fonts", "(qt.qpa.fonts) text\n"),
        ("default", "text\n"),
        (None, "text\n"),
        ("", "() text\n"),
    ],
)
def test_any_category_but_default_prefixes_the_line(
    category: str | None, line: str
) -> None:
    console = _Console()
    forward(_Msg.QtWarningMsg, category, "text", console)
    assert console.calls == [("PrintWarning", line)]


def test_the_installed_handler_receives_qt_messages() -> None:
    console = _Console()
    previous = QtCore.qInstallMessageHandler(message_handler(console))
    try:
        QtCore.qWarning("This plugin does not support raise()")
        QtCore.qWarning("probe")
    finally:
        QtCore.qInstallMessageHandler(previous)
    assert console.calls == [("PrintWarning", "probe\n")]
