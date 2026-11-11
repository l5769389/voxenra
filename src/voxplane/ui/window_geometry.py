"""Keep logical window sizes inside the current screen's usable desktop."""
from PySide6.QtCore import QObject, QPoint, QSize, QTimer
from PySide6.QtGui import QGuiApplication, QWindow
from shiboken6 import isValid


class WindowGeometry(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._screen = None
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_normal)
        window.screenChanged.connect(self._screen_changed)
        window.visibilityChanged.connect(self.fit)
        window.widthChanged.connect(self._enforce_minimum)
        window.heightChanged.connect(self._enforce_minimum)
        # PySide 6.11 can incorrectly parent a QWindow.screen() wrapper to the
        # window, invalidating the shared screen on window destruction. Obtain
        # the screen through the application; screenChanged supplies later moves.
        self._screen_changed(QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen())
        self.initialize()

    def _enforce_minimum(self, *_):
        # Native edge dragging honors QWindow limits; programmatic restores and
        # some window managers do not. Apply the same lower bound to both paths.
        if self._screen is not None and (self.window.width() < self.window.minimumWidth()
                                         or self.window.height() < self.window.minimumHeight()):
            self._fit_timer.start(0)

    def _screen_changed(self, screen):
        if self._screen is not None and isValid(self._screen):
            self._screen.availableGeometryChanged.disconnect(self.fit)
        self._screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self.fit)
        self.fit()

    def client_area(self):
        area = self._screen.availableGeometry()
        margins = self.window.frameMargins()
        return area.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())

    def fit(self, *_):
        if self._screen is None:
            return
        area = self.client_area()
        self.window.setProperty('availableWindowWidth', area.width())
        self.window.setProperty('availableWindowHeight', area.height())
        # Let the QML minimum-size bindings update before clamping normal geometry.
        self._fit_timer.start(0)

    def shutdown(self):
        if self.window is None:
            return
        self._fit_timer.stop()
        if self._screen is not None and isValid(self._screen):
            self._screen.availableGeometryChanged.disconnect(self.fit)
        self._screen = None
        self.window.screenChanged.disconnect(self._screen_changed)
        self.window.visibilityChanged.disconnect(self.fit)
        self.window.widthChanged.disconnect(self._enforce_minimum)
        self.window.heightChanged.disconnect(self._enforce_minimum)
        self.window = None

    def _fit_normal(self):
        if self._screen is None or self.window.visibility() in (QWindow.FullScreen, QWindow.Maximized):
            return
        self._place(self.window.size(), self.window.position())

    def _place(self, size, point=None):
        area = self.client_area()
        size = size.expandedTo(self.window.minimumSize()).boundedTo(area.size())
        self.window.resize(size)
        if point is None:
            point = area.center() - QPoint(size.width() // 2, size.height() // 2)
        self.window.setPosition(max(area.left(), min(point.x(), area.right() - size.width() + 1)),
                                max(area.top(), min(point.y(), area.bottom() - size.height() + 1)))

    def initialize(self, point=None):
        area = self.client_area()
        preferred = QSize(1120, 840) if self.window.property('detached') else QSize(1440, 900)
        # Leave room around normal windows when the desktop permits it.
        preferred = preferred.boundedTo(QSize(max(1, area.width() - 32), max(1, area.height() - 32)))
        self._place(preferred, point)
