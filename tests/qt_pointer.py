"""Pointer movement for hover checks on both native and offscreen Qt windows."""
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtTest import QTest


def activate_window(window):
    """Require the native key window before testing hover, popups or shortcuts."""
    if QGuiApplication.platformName() in ('cocoa', 'windows'):
        assert QTest.qWaitForWindowExposed(window, 3000), 'Native test window was not exposed'
        window.raise_()
        window.requestActivate()
        active = QTest.qWaitForWindowActive(window, 3000)
        assert active, ('Native test window did not become active',
                        window.isVisible(), window.visibility(),
                        QGuiApplication.applicationState(), QGuiApplication.focusWindow(),
                        [(w.title(), w.isVisible(), w.isActive()) for w in QGuiApplication.topLevelWindows()])


def move_pointer(window, position):
    # Cocoa resynchronizes hover with the physical cursor when popup windows
    # appear. Keep it aligned with Qt's synthetic events during native tests.
    if QGuiApplication.platformName() == 'cocoa':
        QCursor.setPos(window.mapToGlobal(position))
    QTest.mouseMove(window, position)
