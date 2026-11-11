"""Import windows use one OS caption close, with identical close semantics."""
import os
import sys

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton
from shiboken6 import delete

from voxplane.ui.dialogs.local_import_dialog import LocalImportDialog
from test_bulk_import import task_dialog
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene


def open_progress(window, panel):
    panel._set_scanning(True)
    panel._import_task_open = True
    panel.importTaskChanged.emit()
    dialog = task_dialog(window)
    native = dialog.findChild(QObject, "importTaskMessage").window()
    assert dialog.findChild(QObject, "importTaskDismiss") is None
    assert native is not window and not native.flags() & Qt.FramelessWindowHint
    return dialog, native


def test_import_window_close_is_guarded_while_busy_and_dismisses_result(scene):
    window, app, warnings = scene
    panel = app.panelController
    dialog, native = open_progress(window, panel)
    try:
        assert not native.close()
        QTest.qWait(30)
        assert panel.importTaskOpen and dialog.property("visible") and native.isVisible()
        QTest.keyClick(native, Qt.Key_Escape)
        assert panel.importTaskOpen
        cancel = dialog.findChild(QObject, "importTaskClose")
        assert cancel.isVisible() and cancel.isEnabled()
        panel._set_scanning(False)
        panel._set_status("导入失败，可重试", True)
        assert native.close()
        wait_until(lambda: not panel.importTaskOpen)
        assert not dialog.property("visible")
        # Reopening after a native close preserves the same result/close wiring.
        panel._set_status("已导入 1 个序列", False)
        panel._import_task_open = True
        panel.importTaskChanged.emit()
        task_dialog(window)
        QTest.keyClick(native, Qt.Key_Escape)
        wait_until(lambda: not panel.importTaskOpen)
    finally:
        panel._set_scanning(False)
        panel.closeImportTask()
    assert not warnings, warnings


def caption_close(window):
    """Inspect real OS caption controls and return their close action."""
    if sys.platform == "darwin":
        from test_window_chrome import _mac_send
        ns_window = _mac_send(int(window.winId()), "window")
        style = _mac_send(ns_window, "styleMask")
        assert style & 1 and style & 2  # Titled and closable, not a drawn QML caption.
        button = _mac_send(ns_window, "standardWindowButton:", 0)
        assert button and not _mac_send(button, "isHidden")
        assert _mac_send(button, "isEnabled")
        return lambda: _mac_send(button, "performClick:", 0)
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.GetSystemMenu.restype = wintypes.HMENU
    user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    user32.GetMenuState.restype = wintypes.UINT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    hwnd = int(window.winId())
    style = user32.GetWindowLongW(hwnd, -16)
    assert style & 0x00C00000 == 0x00C00000  # WS_CAPTION
    assert style & 0x00080000  # WS_SYSMENU: the native top-right close control.
    menu = user32.GetSystemMenu(hwnd, False)
    state = user32.GetMenuState(menu, 0xF060, 0)  # SC_CLOSE, MF_BYCOMMAND
    assert state != 0xFFFFFFFF and not state & 3  # Not disabled or grayed.
    return lambda: user32.SendMessageW(hwnd, 0x112, 0xF060, 0)  # WM_SYSCOMMAND / SC_CLOSE


@pytest.mark.skipif(os.environ.get("VOXPLANE_NATIVE_QA") != "1"
                    or sys.platform not in ("darwin", "win32"),
                    reason="Requires a native macOS or Windows desktop")
def test_native_import_caption_controls_and_result_close(scene, tmp_path):
    assert QGuiApplication.platformName() == ("cocoa" if sys.platform == "darwin" else "windows")
    window, app, warnings = scene
    picker = LocalImportDialog(str(tmp_path))
    picker.show()
    QTest.qWait(100)
    try:
        assert picker.findChild(QPushButton, "importDismiss") is None
        native_close = caption_close(picker.windowHandle())
        assert picker.grab().save(str(tmp_path / "native-import-picker.png"))
        native_close()
        wait_until(lambda: not picker.isVisible())
        assert picker.result() == QDialog.Rejected and not picker.paths
    finally:
        picker.close()
        delete(picker)
    panel = app.panelController
    dialog, native = open_progress(window, panel)
    try:
        native_close = caption_close(native)
        native_close()
        QTest.qWait(50)
        assert panel.importTaskOpen and native.isVisible()
        panel._set_scanning(False)
        panel._set_status("导入失败，可重试", True)
        assert native.grabWindow().save(str(tmp_path / "native-import-result.png"))
        native_close()
        wait_until(lambda: not panel.importTaskOpen)
        assert not dialog.property("visible")
    finally:
        panel._set_scanning(False)
        panel.closeImportTask()
    assert not warnings, warnings
