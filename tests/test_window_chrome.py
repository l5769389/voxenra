"""Branded window chrome and legacy settings migration."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from voxplane.infrastructure import brand_settings
from test_pacs_qml import scene
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import find, click, descendants


def test_title_brand_replaces_sidebar_brand_and_compact_collapse(scene, tmp_path):
    window, app, warnings = scene
    items = list(descendants(window.contentItem()))
    marks = [i for i in items if i.objectName() == "applicationBrandMark"]
    assert len([mark for mark in marks if mark.isVisible()]) == (0 if sys.platform == "win32" else 1)
    assert not any(i.objectName().startswith("windowControl-") for i in items)
    assert not (window.flags() & Qt.FramelessWindowHint)
    assert window.flags() & Qt.WindowMinMaxButtonsHint
    if sys.platform == "darwin":
        assert window.flags() & Qt.WindowFullscreenButtonHint
    else:
        # Windows keeps its native caption buttons and ignores the macOS hint.
        assert window.flags() & Qt.WindowCloseButtonHint
    header = next(i for i in items if i.objectName() == "applicationTitleBar")
    if sys.platform == "win32":
        assert not header.isVisible() and header.height() == 0
        assert not (window.flags() & Qt.ExpandedClientAreaHint)
        assert not (window.flags() & Qt.NoTitleBarBackgroundHint)
    else:
        assert marks[0].mapToScene(QPointF()).y() < header.height()
    assert header.property("color") == window.color()
    assert not any(i.objectName() == "sourceSelectionIndicator" for i in items)
    sidebar = find(window, "sidebarContainer")
    assert sidebar.mapToScene(QPointF()).y() >= header.mapToScene(QPointF(0, header.height())).y()
    click(window, find(window, "sidebarToggle"))
    assert sidebar.width() == 52 and sidebar.isVisible()
    assert header.height() == (0 if sys.platform == "win32" else 32)
    assert find(window, "sidebarToggle").mapToScene(QPointF()).y() > header.height()
    assert find(window, "sidebarToggle").isVisible()
    assert window.grabWindow().save(str(tmp_path / "voxplane-collapsed.png"))
    click(window, find(window, "sidebarToggle"))
    assert sidebar.width() == 300 and sidebar.isVisible()
    assert window.grabWindow().save(str(tmp_path / "voxplane-titlebar.png"))
    assert not warnings, warnings


def test_migration_preserves_old_files_and_never_overwrites_new(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "display-settings.json").write_text('{"window":{"custom":[{"label":"Saved"}]}}')
    (old / "pacs.json").write_text('{"profiles":[{"name":"Saved PACS"}]}')
    brand_settings.migrate_preferences(old, new)
    assert (new / "pacs.json").read_bytes() == (old / "pacs.json").read_bytes()
    assert (new / "display-settings.json").read_bytes() == (old / "display-settings.json").read_bytes()
    (new / "pacs.json").write_text('{"profiles":[]}')
    brand_settings.migrate_preferences(old, new)
    assert (new / "pacs.json").read_text() == '{"profiles":[]}'
    assert "Saved PACS" in (old / "pacs.json").read_text()


def test_storage_identity_uses_voxplane_and_copies_legacy(qt_app, tmp_path, monkeypatch):
    original = qt_app.organizationName(), qt_app.applicationName()
    old, new = tmp_path / "legacy", tmp_path / "voxplane"
    old.mkdir()
    (old / "display-settings.json").write_text('{"layout":{"rightPanelWidth":350}}')
    monkeypatch.setattr(brand_settings, "QStandardPaths", SimpleNamespace(AppConfigLocation=0, AppLocalDataLocation=1,
        writableLocation=lambda _: str(old if qt_app.applicationName() == brand_settings.LEGACY_APPLICATION else new)))
    try:
        brand_settings.configure_storage_identity()
        assert (qt_app.organizationName(), qt_app.applicationName()) == ("VoxPlane", "VoxPlane")
        assert (new / "display-settings.json").read_bytes() == (old / "display-settings.json").read_bytes()
    finally:
        qt_app.setOrganizationName(original[0])
        qt_app.setApplicationName(original[1])


def _mac_send(obj, selector, *args):
    """Exercise our own window's real AppKit controls, without reimplementing them."""
    import ctypes
    lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                            *([ctypes.c_void_p] * len(args)))(("objc_msgSend", lib))
    return send(obj, lib.sel_registerName(selector.encode()), *args)


@pytest.mark.skipif(os.environ.get("VOXPLANE_NATIVE_QA") != "1", reason="Requires native window controls")
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_native_window_maximize_restore_minimize_and_close(scene, tmp_path, theme):
    import sys
    from PySide6.QtCore import QMetaObject
    window, app, warnings = scene
    app.settingsController.setValue('appearance', 'theme', theme)
    window.showNormal()
    QTest.qWait(100)
    if sys.platform == "darwin":
        ns_window = _mac_send(int(window.winId()), "window")
        buttons = [_mac_send(ns_window, "standardWindowButton:", index) for index in range(3)]
        assert _mac_send(ns_window, "titleVisibility") == 1
        assert window.title() == "VoxPlane"
        assert _mac_send(ns_window, "titlebarAppearsTransparent")
        # Verify the actual AppKit appearance, not only the QML header fill.
        name = _mac_send(_mac_send(ns_window, "effectiveAppearance"), "name")
        import ctypes
        pointer = _mac_send(name, "UTF8String")
        assert (b"Dark" in ctypes.string_at(pointer)) == (theme == 'dark')
        assert all(buttons)
        assert all(not _mac_send(button, "isHidden") for button in buttons)
        # Native green button enters a full-screen Space, not a maximized window.
        _mac_send(buttons[2], "performClick:", 0)
    else:
        QMetaObject.invokeMethod(window, "toggleFullScreen")
    wait_until(lambda: window.windowState() == Qt.WindowFullScreen)
    QTest.qWait(1200)
    from PySide6.QtGui import QGuiApplication
    current_screen = QGuiApplication.screenAt(window.position())
    screen = current_screen.geometry()
    # macOS reserves the camera/menu safe area on notched displays even in a Space.
    assert window.width() == screen.width()
    assert window.geometry().bottom() == screen.bottom()
    assert window.height() >= current_screen.availableGeometry().height()
    if sys.platform == "darwin":
        assert _mac_send(ns_window, "titleVisibility") == 1
        assert _mac_send(ns_window, "styleMask") & (1 << 14)  # NSWindowStyleMaskFullScreen
    assert window.grabWindow().save(str(tmp_path / "native-fullscreen.png"))
    QMetaObject.invokeMethod(window, "toggleFullScreen")
    wait_until(lambda: window.windowState() == Qt.WindowNoState)
    QTest.qWait(1200)
    if sys.platform == "darwin":
        assert _mac_send(ns_window, "titleVisibility") == 1
    window.showMaximized()
    wait_until(lambda: window.windowState() == Qt.WindowMaximized)
    window.showNormal()
    QTest.qWait(100)
    if sys.platform == "darwin":
        _mac_send(buttons[1], "performClick:", 0)
    else:
        window.showMinimized()
    wait_until(lambda: window.windowState() == Qt.WindowMinimized)
    window.showNormal()
    QTest.qWait(700)
    if sys.platform == "darwin":
        _mac_send(buttons[0], "performClick:", 0)
    else:
        window.close()
    assert not window.isVisible()
    assert not warnings, warnings


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("VOXPLANE_NATIVE_QA") != "1",
                    reason="Requires the native Windows desktop")
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_windows_native_caption_has_matching_controls_and_drag_hit_target(scene, tmp_path, theme):
    import ctypes
    from ctypes import wintypes
    from PySide6.QtGui import QGuiApplication
    window, app, warnings = scene
    app.settingsController.setValue('appearance', 'theme', theme)
    window.showNormal()
    window.requestActivate()
    QTest.qWait(200)
    assert QGuiApplication.platformName() == "windows"
    assert QGuiApplication.styleHints().colorScheme() == (Qt.ColorScheme.Dark if theme == 'dark' else Qt.ColorScheme.Light)
    assert not any(i.objectName() == "applicationBrandMark" and i.isVisible()
                   for i in descendants(window.contentItem()))
    hwnd = int(window.winId())
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    assert title.value == "VoxPlane"
    rect, client = wintypes.RECT(), wintypes.POINT(0, 0)
    assert user32.GetWindowRect(hwnd, ctypes.byref(rect))
    assert user32.ClientToScreen(hwnd, ctypes.byref(client))
    assert client.y > rect.top
    x, y = (rect.left + rect.right) // 2, (rect.top + client.y) // 2
    point = (x & 0xffff) | ((y & 0xffff) << 16)
    # This is the real OS hit test, not a QML mouse area's simulated drag.
    assert user32.SendMessageW(hwnd, 0x84, 0, point) == 2  # WM_NCHITTEST / HTCAPTION
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.DwmGetWindowAttribute.restype = ctypes.c_int32
    value = ctypes.c_uint32()
    result = dwm.DwmGetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)
    if result != 0:
        result = dwm.DwmGetWindowAttribute(hwnd, 19, ctypes.byref(value), 4)
    assert result == 0 and value.value == (1 if theme == 'dark' else 0)
    if sys.getwindowsversion().build >= 22000:
        assert dwm.DwmGetWindowAttribute(hwnd, 35, ctypes.byref(value), 4) == 0
        assert value.value == (0x00171310 if theme == 'dark' else 0x00f5f0e9)
    # Send real pointer input from a helper process: Windows' modal move loop
    # must continue receiving input while the Qt test thread pumps OS messages.
    import subprocess
    helper = subprocess.Popen([sys.executable, "-c", """
import ctypes, sys, time
u = ctypes.WinDLL('user32')
u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
u.SetForegroundWindow(int(sys.argv[1]))
x, y = int(sys.argv[2]), int(sys.argv[3])
u.SetCursorPos(x, y)
time.sleep(.15)
u.mouse_event(2, 0, 0, 0, 0)
try:
    time.sleep(.15)
    for step in range(1, 9):
        u.SetCursorPos(x + step * 8, y + step * 4)
        time.sleep(.04)
finally:
    u.mouse_event(4, 0, 0, 0, 0)
""", str(hwnd), str(x), str(y)])
    try:
        wait_until(lambda: helper.poll() is not None)
        assert helper.returncode == 0
    finally:
        if helper.poll() is None:
            helper.kill()
        helper.wait(timeout=10)
        user32.mouse_event(4, 0, 0, 0, 0)
    moved = wintypes.RECT()
    assert user32.GetWindowRect(hwnd, ctypes.byref(moved))
    assert moved.left - rect.left >= 30 and moved.top - rect.top >= 15
    # Double-clicking that native caption must maximize, then restore normally.
    user32.SendMessageW(hwnd, 0xA3, 2, point)  # WM_NCLBUTTONDBLCLK / HTCAPTION
    wait_until(lambda: window.windowState() == Qt.WindowMaximized)
    window.showNormal()
    wait_until(lambda: window.windowState() == Qt.WindowNoState)
    QTest.qWait(150)
    assert window.grabWindow().save(str(tmp_path / "windows-native-caption-content.png"))
    assert not warnings, "\n".join(warnings)
