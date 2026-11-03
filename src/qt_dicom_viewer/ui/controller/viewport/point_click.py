"""Distinguish a point placement from the first half of a finish gesture."""
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from shiboken6 import isValid


class PendingPointClick(QObject):
    """Only observe a window while one point click is undecided."""

    def __init__(self, parent):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self.confirm)
        self._window = self._apply = self._cancel = None

    def queue(self, window, position, apply, cancel=None):
        self.confirm()  # A distinct single tap, even during rapid point placement.
        self._window, self._position, self._apply = window, position, apply
        self._cancel = cancel
        window.installEventFilter(self)
        self._timer.start(QGuiApplication.styleHints().mouseDoubleClickInterval())

    def _reset(self):
        self._timer.stop()
        if self._window is not None and isValid(self._window):
            self._window.removeEventFilter(self)
        self._window = self._apply = self._cancel = None

    def discard(self):
        cancel = self._cancel
        self._reset()
        if cancel is not None:
            cancel()

    def confirm(self):
        apply = self._apply
        self._reset()
        if apply is not None:
            apply()

    def eventFilter(self, window, event):
        # Deliver the preceding point before Enter, a wheel change, or a press
        # elsewhere (including the Done button) acts on the document.
        kind = event.type()
        if kind in (QEvent.KeyPress, QEvent.ShortcutOverride, QEvent.Wheel, QEvent.WindowDeactivate):
            self.confirm()
        elif kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            d = event.position() - self._position
            if (event.button() != Qt.LeftButton or
                    d.x()**2 + d.y()**2 >= QGuiApplication.styleHints().mouseDoubleClickDistance()**2):
                self.confirm()
        elif kind in (QEvent.Hide, QEvent.Close):
            self.discard()
        return False
