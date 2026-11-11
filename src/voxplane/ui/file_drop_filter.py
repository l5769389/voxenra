"""Route OS file drops on native VTK children through the same import controller."""

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication


class NativeFileDropFilter(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() not in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            return False
        host = getattr(watched, "host", None)
        if (
            host is None
            or not any(getattr(host, "controller", None) is session.activeViewport
                       for session in self.app.windowManager.sessions.values())
        ):
            return False
        panel = self.app.panelController
        urls = event.mimeData().urls()
        if (
            not self.app.pacsController.localEnabled
            or not panel.canImportUrls(urls)
            or not event.possibleActions() & Qt.CopyAction
        ):
            event.ignore()
            return True
        if event.type() == QEvent.Drop:
            if not panel.importUrls(urls):
                event.ignore()
                return True
            self.app.windowManager.showMainWindow()
        event.setDropAction(Qt.CopyAction)
        event.accept()
        return True

    def shutdown(self):
        QApplication.instance().removeEventFilter(self)
