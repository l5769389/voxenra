"""One workspace settings object shared by all tabs and viewports."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from copy import deepcopy
import json
from pathlib import Path
import uuid

from PySide6.QtCore import QObject, Property, Signal, Slot, QStandardPaths, QSaveFile, QIODevice, QUrl

from PySide6.QtGui import QDesktopServices

from qt_dicom_viewer.settings import window_presets as preset_file
from qt_dicom_viewer import __version__
from qt_dicom_viewer.core.color_maps import COLOR_MAPS
from qt_dicom_viewer.core.measurement_format import format_measurement
from qt_dicom_viewer.preset import CT_WINDOW_PRESETS
from qt_dicom_viewer.settings.preferences import DEFAULTS, CORNER_FIELDS, CORNERS, METRICS, normalize_settings, validate_value
from qt_dicom_viewer.i18n.widgets import QFileDialog


class SettingsController(QObject):
    _i18n_colorMaps = Signal()
    _i18n_cornerFields = Signal()
    _i18n_message = Signal()
    _i18n_roiFields = Signal()
    _i18n_values = Signal()
    _i18n_windowTemplates = Signal()


    categoryChanged = Signal()
    changed = Signal()
    sectionChanged = Signal(str)
    messageChanged = Signal()

    def __init__(self, parent=None, *, path=None):
        super().__init__(parent)
        self._path = None if path is False else Path(path) if path else Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / "display-settings.json"
        self._active_category = "sources"
        self._data = deepcopy(DEFAULTS)
        self._message = ""
        if self._path and self._path.exists():
            try:
                self._data = normalize_settings(json.loads(self._path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                self._message = _msg('text.0521')

        self._window_path = self._path.with_name("window-presets.json") if self._path else None
        self._window_entries = preset_file.from_legacy(self._data["window"])
        self._window_revision = None
        self._window_file_valid = True
        if self._window_path:
            try:
                if self._window_path.exists():
                    self._window_entries, self._window_revision = preset_file.read_document(self._window_path)
                else:
                    self._window_revision = preset_file.write_document(self._window_path, self._window_entries)
                self._data["window"] = preset_file.legacy_view(self._window_entries)
            except (OSError, ValueError) as exc:
                self._window_file_valid = False
                self._message = _msg("windowFile.invalid", value1=str(exc))

        self._message_is_error = bool(self._message)

    @Property(str, constant=True)
    def applicationVersion(self):
        return __version__

    @Property(str, notify=categoryChanged)
    def activeCategory(self):
        return self._active_category

    @Slot(str)
    def selectCategory(self, category):
        if category in ("sources", *DEFAULTS) and category != self._active_category:
            self._active_category = category
            self.categoryChanged.emit()

    @_TextProperty('QVariantMap', notify=_i18n_values, notify_name='_i18n_values', source_notify='changed')
    def values(self):
        return deepcopy(self._data)

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='messageChanged')
    def message(self):
        return self._message

    @Property(bool, notify=messageChanged)
    def messageIsError(self):
        return self._message_is_error

    @Property(str, constant=True)
    def defaultExportDirectory(self):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return str((Path(documents) if documents else Path.home() / "Documents") / "Voxenra" / "Exports")

    @Property(str, notify=changed)
    def exportDirectory(self):
        return self._data["export"]["directory"] or self.defaultExportDirectory

    @Slot()
    def chooseExportDirectory(self):
        folder = QFileDialog.getExistingDirectory(None, _msg('text.0522'), self.exportDirectory)
        if folder:
            self.setValue("export", "directory", folder)

    @_TextProperty('QVariantList', notify=_i18n_colorMaps, notify_name='_i18n_colorMaps')
    def colorMaps(self):
        from qt_dicom_viewer.core.pseudocolor import color_lut
        return [dict(key=k, label=label, colors=["#{:02x}{:02x}{:02x}".format(*rgb)
                    for rgb in color_lut(k)]) for k, (label, _) in COLOR_MAPS.items()]

    @_TextProperty('QVariantList', notify=_i18n_cornerFields, notify_name='_i18n_cornerFields')
    def cornerFields(self):
        return [dict(key=k, label=v) for k, v in CORNER_FIELDS.items()]

    @_TextProperty('QVariantList', notify=_i18n_roiFields, notify_name='_i18n_roiFields')
    def roiFields(self):
        return [dict(key=k, label=v) for k, v in METRICS.items()]

    @_TextProperty('QVariantList', notify=_i18n_windowTemplates, notify_name='_i18n_windowTemplates', source_notify='changed')
    def windowTemplates(self):
        labels = {p.preset_id: p.label for p in CT_WINDOW_PRESETS}
        return [dict(p, label=p["label"] or labels.get(p["presetId"], p["presetId"]),
                     builtin=p["presetId"] in preset_file.BUILTIN_IDS) for p in self._window_entries]

    @Property(str, constant=True)
    def windowPresetsPath(self):
        return str(self._window_path) if self._window_path else ""

    @Slot(result=bool)
    def openWindowPresetsLocation(self):
        if not self._window_path:
            return False
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._window_path.parent)))
        return True if opened else self._error(_msg("windowFile.openFailed"))

    @Slot(result=bool)
    def reloadWindowPresets(self):
        if not self._window_path:
            return False
        try:
            entries, revision = preset_file.read_document(self._window_path)
        except (OSError, ValueError) as exc:
            return self._error(_msg("windowFile.invalid", value1=str(exc)))
        self._window_entries, self._window_revision = entries, revision
        self._window_file_valid = True
        self._data["window"] = preset_file.legacy_view(entries)
        self._error(_msg("windowFile.loaded"), is_error=False)
        self.changed.emit()
        self.sectionChanged.emit("window")
        return True

    def _save_window_entries(self, entries):
        try:
            entries = preset_file.validate_document(dict(schemaVersion=1, presets=entries))
            if self._window_path:
                # Do not overwrite edits made in an external editor since loading.
                if (not self._window_file_valid or self._window_path.stat().st_size > preset_file.MAX_BYTES
                        or self._window_path.read_bytes() != self._window_revision):
                    return self._error(_msg("windowFile.changed"))
                revision = preset_file.write_document(self._window_path, entries)
                self._window_revision = revision
        except (OSError, ValueError) as exc:
            return self._error(_msg("windowFile.invalid", value1=str(exc)))
        self._window_entries = entries
        self._data["window"] = preset_file.legacy_view(entries)
        self._error("")
        self.changed.emit()
        self.sectionChanged.emit("window")
        return True

    @property
    def window_presets(self):
        return [p for p in self.windowTemplates if p["enabled"]]

    @Slot("QVariant", int, result=str)
    def formatMeasurement(self, value, decimal_places):
        return format_measurement(value, decimal_places)

    def section(self, name):
        return deepcopy(self._data[name])

    def _error(self, message, *, is_error=True):
        self._message_is_error = bool(message) and is_error
        self._message = message
        self.messageChanged.emit()
        return False

    def _commit(self, section, candidate):
        if section == "window":
            state = candidate["window"]
            entries = [dict(p, enabled=p["presetId"] not in state["hidden"])
                       for p in self._window_entries if p["presetId"] in preset_file.BUILTIN_IDS]
            return self._save_window_entries(entries + state["custom"])
        if self._path:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                target = QSaveFile(str(self._path))
                # Remove legacy presets only after the separate file is usable.
                # A failed first migration must survive saving unrelated settings.
                saved = {key: value for key, value in candidate.items()
                         if key != "window" or not self._window_file_valid}
                payload = json.dumps({"schemaVersion": 1, **saved}, ensure_ascii=False, indent=2).encode("utf-8")
                if not target.open(QIODevice.WriteOnly) or target.write(payload) != len(payload) or not target.commit():
                    raise OSError("Cannot save settings")
            except OSError:
                return self._error(_msg('text.0523'))
        self._data = candidate
        self._error("")
        self.changed.emit()
        self.sectionChanged.emit(section)
        return True

    @Slot(str, str, "QVariant", result=bool)
    def setValue(self, section, key, value):
        # Compatibility for callers using the former individual dimension keys.
        if section == "roi" and key in ("width", "height"):
            key = "dimensions"
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        try:
            value = validate_value(section, key, value)
        except (ValueError, TypeError) as exc:
            return self._error(error_message(exc))
        if value == self._data[section][key]:
            self._error("")
            return True
        candidate = deepcopy(self._data)
        candidate[section][key] = value
        return self._commit(section, candidate)

    @Slot(str, result=bool)
    def resetSection(self, section):
        if section == "window":
            return self._save_window_entries(preset_file.from_legacy(DEFAULTS["window"]))
        if section not in DEFAULTS:
            return self._error(_msg('text.0524'))
        candidate = deepcopy(self._data)
        candidate[section] = deepcopy(DEFAULTS[section])
        return self._commit(section, candidate)

    @Slot(str, str, float, float, result=bool)
    def saveWindowTemplate(self, identifier, label, width, center):
        entries = deepcopy(self._window_entries)
        item = dict(presetId=identifier or "custom-" + str(uuid.uuid4()), label=label,
                    width=width, center=center, enabled=True)
        if identifier:
            if not any(p["presetId"] == identifier for p in entries):
                return self._error(_msg('text.0525'))
            entries = [dict(item, enabled=p["enabled"]) if p["presetId"] == identifier else p for p in entries]
        else:
            entries.append(item)
        return self._save_window_entries(entries)

    @Slot(str, result=bool)
    def deleteWindowTemplate(self, identifier):
        return self._save_window_entries([p for p in self._window_entries if p["presetId"] != identifier])

    @Slot(str, bool, result=bool)
    def enableWindowTemplate(self, identifier, enabled):
        return self._save_window_entries([dict(p, enabled=enabled) if p["presetId"] == identifier else p for p in self._window_entries])

    @Slot(str, str, result=bool)
    def addCornerField(self, corner, field):
        if corner not in CORNERS or field not in CORNER_FIELDS:
            return self._error(_msg('text.0526'))
        entries = self._data["corners"][corner]
        if field in entries:
            return self._error(_msg('text.0527'))
        return self.setValue("corners", corner, entries + [field])

    @Slot(str, int, int, result=bool)
    def moveCornerField(self, corner, index, offset):
        if corner not in CORNERS:
            return False
        entries = list(self._data["corners"][corner])
        dest = index + offset
        if not 0 <= index < len(entries) or not 0 <= dest < len(entries):
            return False
        entries.insert(dest, entries.pop(index))
        return self.setValue("corners", corner, entries)

    @Slot(str, int, result=bool)
    def removeCornerField(self, corner, index):
        if corner not in CORNERS:
            return False
        entries = list(self._data["corners"][corner])
        if not 0 <= index < len(entries):
            return False
        entries.pop(index)
        return self.setValue("corners", corner, entries)


def resolve_settings(parent):
    """Standalone controllers use isolated defaults; the app owns persistence."""
    ancestor = parent
    while ancestor is not None:
        settings = getattr(ancestor, "_settings_controller", None)
        if settings is not None:
            return settings
        ancestor = ancestor.parent()
    return SettingsController(parent, path=False)
