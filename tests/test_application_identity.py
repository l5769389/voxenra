"""Application icon inheritance and Windows taskbar identity."""
import ctypes
from types import SimpleNamespace

from PySide6.QtGui import QWindow

from voxplane import app as application
from test_measurement_qml import qt_app


def test_new_windows_inherit_brand_icon_without_changing_settings_identity(qt_app):
    previous_icon = qt_app.windowIcon()
    previous_display_name = qt_app.applicationDisplayName()
    settings_identity = (qt_app.organizationName(), qt_app.applicationName())
    try:
        application.configure_application_identity(qt_app)
        window = QWindow()
        assert not qt_app.windowIcon().isNull()
        assert not window.icon().isNull()
        assert not window.icon().pixmap(32, 32).isNull()
        assert qt_app.applicationDisplayName() == "VoxPlane"
        assert (qt_app.organizationName(), qt_app.applicationName()) == settings_identity
    finally:
        qt_app.setWindowIcon(previous_icon)
        qt_app.setApplicationDisplayName(previous_display_name)


def test_windows_process_identity_matches_installer_shortcuts(monkeypatch):
    calls = []
    def set_identity(value):
        calls.append(value)
        return 0
    monkeypatch.setattr(application.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=set_identity)), raising=False)
    application.configure_process_identity()
    assert calls == ["com.junliu.voxplane"]
    assert set_identity.argtypes == [ctypes.c_wchar_p]
