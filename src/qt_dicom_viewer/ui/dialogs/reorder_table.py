"""Row reorder gesture: preview while dragging, commit only on release."""
from PySide6.QtCore import Qt, Signal, QRect, QTimer, QEvent
from PySide6.QtWidgets import QApplication, QTableWidget, QRubberBand


class ReorderTable(QTableWidget):
    rowMoveRequested = Signal(str, int)

    def __init__(self, columns, parent=None):
        super().__init__(0, columns, parent)
        self._source = -1
        self._identifier = ''
        self._canceled_id = ''
        self._start = None
        self._dragging = False
        self._position = None
        self._watched_window = None
        self._marker = QRubberBand(QRubberBand.Line, self.viewport())
        self._scroll = QTimer(self)
        self._scroll.setInterval(40)
        self._scroll.timeout.connect(self._autoscroll)

    def _cancel(self):
        self._source = -1
        self._dragging = False
        self._start = None
        self._marker.hide()
        self._scroll.stop()
        self.viewport().unsetCursor()

    def mousePressEvent(self, event):
        self._cancel()
        self._canceled_id = ''
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._source = self.rowAt(event.position().toPoint().y())
            if self._source >= 0:
                self._identifier = self.item(self._source, 0).data(Qt.UserRole)
                self._start = event.position().toPoint()

    def _insertion(self, position):
        row = self.rowAt(position.y())
        if row < 0:
            return self.rowCount()
        rect = self.visualRect(self.model().index(row, 0))
        return row + (position.y() >= rect.center().y())

    def _preview(self):
        slot = self._insertion(self._position)
        y = (self.visualRect(self.model().index(slot, 0)).top() if slot < self.rowCount()
             else self.visualRect(self.model().index(self.rowCount() - 1, 0)).bottom())
        self._marker.setGeometry(QRect(0, y, self.viewport().width(), 3))
        self._marker.show()

    def mouseMoveEvent(self, event):
        if self._start is None:
            return super().mouseMoveEvent(event)
        self._position = event.position().toPoint()
        if (self._position - self._start).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
        if self._dragging:
            self.viewport().setCursor(Qt.ClosedHandCursor)
            self._preview()
            self._scroll.start()
        event.accept()

    def _autoscroll(self):
        if self._position is None:
            return
        direction = -1 if self._position.y() < 18 else 1 if self._position.y() > self.viewport().height() - 18 else 0
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + direction * bar.singleStep())
        self._preview()

    def mouseReleaseEvent(self, event):
        if self._canceled_id:
            identifier = self._canceled_id
            self._canceled_id = ''
            super().mouseReleaseEvent(event)
            for row in range(self.rowCount()):
                if self.item(row, 0).data(Qt.UserRole) == identifier:
                    self.selectRow(row)
                    break
            return
        if self._dragging:
            position = event.position().toPoint()
            slot = self._insertion(position)
            destination = slot - (slot > self._source)
            offset, identifier = destination - self._source, self._identifier
            valid = self.viewport().rect().contains(position)
            source = self._source
            super().mouseReleaseEvent(event)
            self.selectRow(source)
            self._cancel()
            if valid and offset:
                self.rowMoveRequested.emit(identifier, offset)
            event.accept()
        else:
            self._cancel()
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._start is not None:
            self._canceled_id = self._identifier
            self._cancel()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _abort_gesture(self):
        if self._start is not None:
            self._canceled_id = self._identifier
        self._cancel()

    def showEvent(self, event):
        super().showEvent(event)
        self._watched_window = self.window()
        self._watched_window.installEventFilter(self)

    def hideEvent(self, event):
        self._abort_gesture()
        if self._watched_window is not None:
            self._watched_window.removeEventFilter(self)
            self._watched_window = None
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched is self._watched_window and event.type() == QEvent.WindowDeactivate:
            self._abort_gesture()
        return super().eventFilter(watched, event)

    def viewportEvent(self, event):
        if event.type() == QEvent.UngrabMouse and hasattr(self, '_start'):
            self._abort_gesture()
        return super().viewportEvent(event)
