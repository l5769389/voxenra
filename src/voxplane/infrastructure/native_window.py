"""Platform chrome adjustments that have no public QWindow equivalent."""
import ctypes
import logging
import sys

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QPalette, QWindow
from shiboken6 import isValid

logger = logging.getLogger(__name__)


class NativeWindowChrome(QObject):
    """Keep native controls and match each platform's caption to the current UI.

    Windows uses a complete native caption for dragging, snap and system buttons.
    Cocoa keeps native traffic lights alongside the QML brand and hides its title.
    Reapply after Qt updates the platform window, including full-screen changes.
    """

    def __init__(self, window: QWindow, parent: QObject, *, custom_title=True):
        super().__init__(parent)
        self._window = window
        self._custom_title = custom_title
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply)
        platform = QGuiApplication.platformName()
        self._cocoa_enabled = sys.platform == "darwin" and platform == "cocoa"
        self._windows_enabled = sys.platform == "win32" and platform == "windows"
        self._enabled = self._cocoa_enabled or self._windows_enabled
        if self._windows_enabled:
            # Qt must also know the theme, otherwise a later activation/theme
            # event can restore light native caption-button hover backgrounds.
            self._dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            self._dwm_set_attribute = self._dwm.DwmSetWindowAttribute
            self._dwm_set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                ctypes.c_void_p, ctypes.c_uint]
            self._dwm_set_attribute.restype = ctypes.c_int32
        if self._cocoa_enabled:
            self._objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
            self._objc.sel_registerName.restype = ctypes.c_void_p
            self._objc.sel_registerName.argtypes = [ctypes.c_char_p]
            self._view_window = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
                ("objc_msgSend", self._objc))
            self._set_visibility = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(
                ("objc_msgSend", self._objc))
            self._objc.objc_getClass.restype = ctypes.c_void_p
            self._objc.objc_getClass.argtypes = [ctypes.c_char_p]
            self._get_object = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
                ("objc_msgSend", self._objc))
            self._set_object = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
                ("objc_msgSend", self._objc))
            self._set_bool = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(
                ("objc_msgSend", self._objc))
            self._string = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(
                ("objc_msgSend", self._objc))
            self._color = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double)(("objc_msgSend", self._objc))
            self._window_selector = self._objc.sel_registerName(b"window")
            self._visibility_selector = self._objc.sel_registerName(b"setTitleVisibility:")
        if self._enabled:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._schedule)
            window.installEventFilter(self)
            window.windowTitleChanged.connect(self._schedule)
            window.visibilityChanged.connect(self._schedule)
            window.activeChanged.connect(self._schedule)
            if hasattr(window, "colorChanged"):
                window.colorChanged.connect(self._schedule)
            self._schedule()

    def _schedule(self, *_args):
        if self._enabled:
            self._timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Show, QEvent.WinIdChange, QEvent.WindowStateChange,
                            QEvent.ThemeChange, QEvent.ApplicationPaletteChange):
            self._schedule()
        return False

    def _apply(self):
        if not self._enabled or not isValid(self._window):
            return
        try:
            if self._windows_enabled:
                self._apply_windows()
                return
            ns_view = int(self._window.winId())
            if ns_view:
                ns_window = self._view_window(ns_view, self._window_selector)
                if ns_window:
                    # Dialogs retain their native caption; app windows draw a QML title.
                    self._set_visibility(ns_window, self._visibility_selector, int(self._custom_title))
                    sel = self._objc.sel_registerName
                    # Qt's transparent-title hint alone can leave Cocoa's light
                    # frame/background exposed during resize or activation.
                    name = self._string(self._objc.objc_getClass(b"NSString"),
                        sel(b"stringWithUTF8String:"), b"NSAppearanceNameAqua" if self._is_light() else b"NSAppearanceNameDarkAqua")
                    appearance = self._get_object(self._objc.objc_getClass(b"NSAppearance"),
                        sel(b"appearanceNamed:"), name)
                    if appearance:
                        self._set_object(ns_window, sel(b"setAppearance:"), appearance)
                    self._set_bool(ns_window, sel(b"setTitlebarAppearsTransparent:"), self._custom_title)
                    color = self._window.color()
                    background = self._color(self._objc.objc_getClass(b"NSColor"),
                        sel(b"colorWithSRGBRed:green:blue:alpha:"),
                        color.redF(), color.greenF(), color.blueF(), 1.0)
                    self._set_object(ns_window, sel(b"setBackgroundColor:"), background)
        except (OSError, TypeError, ValueError):
            logger.exception("Unable to apply native window appearance")

    def _set_windows_attribute(self, hwnd, attribute, value):
        data = ctypes.c_uint32(value)
        return self._dwm_set_attribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

    def _is_light(self):
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light

    def _apply_windows(self):
        hwnd = int(self._window.winId())
        if not hwnd:
            return
        # DWMWA_USE_IMMERSIVE_DARK_MODE; pre-20H1 Windows 10 used attribute 19.
        dark = 0 if self._is_light() else 1
        if self._set_windows_attribute(hwnd, 20, dark) != 0:
            self._set_windows_attribute(hwnd, 19, dark)
        background = self._window.color()
        caption = background.red() | (background.green() << 8) | (background.blue() << 16)
        # COLORREF is 0x00BBGGRR. Windows 11 supports these exact caption colors;
        # older Windows keeps the selected native palette when unsupported.
        self._set_windows_attribute(hwnd, 35, caption)  # DWMWA_CAPTION_COLOR
        foreground = QGuiApplication.palette().color(QPalette.WindowText)
        text = foreground.red() | (foreground.green() << 8) | (foreground.blue() << 16)
        self._set_windows_attribute(hwnd, 36, text)
