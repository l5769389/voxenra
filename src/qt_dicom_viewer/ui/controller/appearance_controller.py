"""One palette for QML, widget dialogs and native captions; image colors stay independent."""
from PySide6.QtCore import QObject, Property, Signal
from PySide6.QtGui import QGuiApplication, QPalette, QColor
from PySide6.QtCore import Qt

from qt_dicom_viewer.ui.theme_palette import palette_for

# Compatibility exports for widget callers; all values come from palettes.json.
DARK = palette_for("dark")
LIGHT = palette_for("light")

_current = None


def current_colors():
    from shiboken6 import isValid
    owner = _current() if _current is not None else None
    return owner.colors if owner is not None and isValid(owner) else dict(DARK)


class AppearanceController(QObject):
    changed = Signal()
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        global _current
        from weakref import ref
        _current = ref(self)
        self.settings = settings
        self._theme = settings.section('appearance')['theme']
        settings.sectionChanged.connect(self._setting_changed)
        self._apply()

    @Property(str, notify=changed)
    def theme(self): return self._theme

    @Property('QVariantMap', notify=changed)
    def colors(self): return palette_for(self._theme)

    def _setting_changed(self, section):
        if section == 'appearance':
            theme = self.settings.section('appearance')['theme']
            if theme != self._theme:
                self._theme = theme
                self._apply()
                self.changed.emit()

    def _apply(self):
        app = QGuiApplication.instance()
        if app is None: return
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if self._theme == 'light' else Qt.ColorScheme.Dark)
        c, palette = self.colors, QPalette()
        for role, key in {
            QPalette.Window: 'panelBackground', QPalette.WindowText: 'textPrimary',
            QPalette.Base: 'controlBackground', QPalette.AlternateBase: 'panelBackgroundSoft',
            QPalette.Text: 'textPrimary', QPalette.Button: 'controlBackground', QPalette.ButtonText: 'textPrimary',
            QPalette.Highlight: 'selectionBackground', QPalette.HighlightedText: 'textPrimary',
            QPalette.ToolTipBase: 'elevatedBackground', QPalette.ToolTipText: 'textPrimary',
            QPalette.Link: 'primaryColor', QPalette.PlaceholderText: 'textSubtle'
        }.items():
            palette.setColor(role, QColor(c[key]))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(c['textDisabled']))
        app.setPalette(palette)
