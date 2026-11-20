"""The GUI tier's Qt message handler (:mod:`tests.qt_messages`) in place:
offscreen plugin warnings stay out of FreeCAD's console, other Qt messages
reach it."""

import uuid

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtTest, QtWidgets

from tests.qt_messages import UNSUPPORTED_PLUGIN_PREFIX, message_handler

_PLUGIN_WARNING = "This plugin does not support"
# FreeCAD 1.1.3's Notification Area shows its popup when a 250 ms timer,
# restarted by every notification, runs out.
_POPUP_DELAY_MS = 250


def _report_view() -> QtWidgets.QTextEdit:
    view = FreeCADGui.getMainWindow().findChild(QtWidgets.QTextEdit, "Report view")
    assert isinstance(view, QtWidgets.QTextEdit)
    return view


def _report_text() -> str:
    """The Report view's text, once queued console output has been
    delivered. Startup output emitted before the handler was installed is
    still queued when the first test runs."""
    QtWidgets.QApplication.processEvents()
    return _report_view().toPlainText()


def _report_text_after(before: int) -> str:
    return _report_text()[before:]


def test_raise_warns_nothing_and_other_qt_warnings_still_reach_the_report_view() -> (
    None
):
    before = len(_report_text())
    widget = QtWidgets.QWidget()
    seen: list[str] = []

    def record(
        msg_type: QtCore.QtMsgType, context: QtCore.QMessageLogContext, text: str
    ) -> None:
        seen.append(text)

    try:
        widget.show()
        QtWidgets.QApplication.processEvents()
        # Pins the wording the filter matches: a Qt that rewords the warning
        # fails here instead of leaking it past the filter.
        QtCore.qInstallMessageHandler(record)
        try:
            widget.raise_()
            QtWidgets.QApplication.processEvents()
        finally:
            QtCore.qInstallMessageHandler(message_handler(FreeCAD.Console))
        assert any(text.startswith(UNSUPPORTED_PLUGIN_PREFIX) for text in seen), seen
        widget.raise_()
    finally:
        widget.deleteLater()
    assert _PLUGIN_WARNING not in _report_text_after(before)

    marker = f"qt-message-marker-{uuid.uuid4().hex}"
    QtCore.qWarning(marker)
    assert marker in _report_text_after(before)


def test_a_repeated_warning_with_the_main_window_active_returns() -> None:
    """The path the handler guards: FreeCAD 1.1.3 shows a popup for a
    message identical to the previous one, popups off or not, while its
    main window is active.

    On the x86_64 dev VM this test reaches the popup: a visible
    ``NotificationBox_label`` was found at its end in three runs out of
    three. With the handler removed it fails without hanging, because
    offscreen's other plugin warnings reach the console between the two
    sends, and the second no longer repeats the last message."""
    main_window = FreeCADGui.getMainWindow()
    main_window.raise_()
    before = len(_report_text())
    warning = f"repeated-warning-{uuid.uuid4().hex}\n"
    for _ in range(2):
        # Activated before each warning: offscreen, a main window activated
        # once during a test's first events was found inactive again 50 ms
        # later, and the popup needs it active when the timer runs out.
        # raise_() stays outside the loop: without the handler its warning
        # would come between the two sends, and the second would no longer
        # repeat the last message.
        main_window.activateWindow()
        QtWidgets.QApplication.processEvents()
        FreeCAD.Console.PrintWarning(warning)
        QtTest.QTest.qWait(2 * _POPUP_DELAY_MS)
    assert _PLUGIN_WARNING not in _report_text_after(before)
