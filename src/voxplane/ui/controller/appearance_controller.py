"""One palette for QML, widget dialogs and native captions; image colors stay independent."""
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QPalette, QColor

from voxplane.ui.theme_palette import palette_for

# Compatibility exports for widget callers; all values come from palettes.json.
DARK = palette_for("dark")
LIGHT = palette_for("light")

_current = None


def current_appearance():
    from shiboken6 import isValid
    owner = _current() if _current is not None else None
    return owner if owner is not None and isValid(owner) else None


def current_colors():
    owner = current_appearance()
    return owner.colors if owner is not None else dict(DARK)


class AppearanceController(QObject):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        global _current
        from weakref import ref
        _current = ref(self)
        self.settings = settings
        self._theme = None
        self._palette_theme = None
        settings.sectionChanged.connect(self._setting_changed)
        app = QGuiApplication.instance()
        if app is not None:
            # Read the latest scheme after Qt has processed the native palette change.
            app.styleHints().colorSchemeChanged.connect(self._system_scheme_changed, Qt.QueuedConnection)
        self._setting_changed('appearance')

    @Property(str, notify=changed)
    def theme(self): return self._theme

    @Property('QVariantMap', notify=changed)
    def colors(self): return palette_for(self._palette_theme)

    @Slot(str)
    def _setting_changed(self, section):
        if section != 'appearance':
            return
        theme = self.settings.section('appearance')['theme']
        if theme == self._theme:
            return
        self._theme = theme
        app = QGuiApplication.instance()
        if app is not None:
            if theme == 'system':
                app.styleHints().unsetColorScheme()
            else:
                app.styleHints().setColorScheme(Qt.ColorScheme.Light if theme == 'light' else Qt.ColorScheme.Dark)
        self._refresh_palette()
        self.changed.emit()

    @Slot()
    def _system_scheme_changed(self):
        if self._theme == 'system' and self._refresh_palette():
            self.changed.emit()

    def _refresh_palette(self):
        app = QGuiApplication.instance()
        theme = self._theme
        if theme == 'system':
            theme = 'light' if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Light else 'dark'
        if theme == self._palette_theme:
            return False
        self._palette_theme = theme
        if app is not None:
            self._apply_palette(app)
        return True

    def _apply_palette(self, app):
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
