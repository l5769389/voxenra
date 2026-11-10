"""Recent paths are committed only after the existing local scan succeeds."""
from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property
from qt_dicom_viewer.settings.favorite_directories import path_key
from qt_dicom_viewer.settings.recent_image_paths import RecentImagePathsStore, MAX_RECENT_PATHS


class RecentImagePathsController(QObject):
    changed = Signal()
    messageChanged = Signal()
    _i18n_message = Signal()

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self._store = RecentImagePathsStore(path)
        self._message = ''

    @Property('QVariantList', notify=changed)
    def items(self):
        return list(self._store.items)

    @property
    def last_directory(self):
        return self._store.directory

    @translated_property(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='messageChanged')
    def message(self):
        return self._message

    def _commit(self, items, directory):
        try:
            self._store.save(items, directory)
        except OSError:
            self._message = _msg('recent.saveFailed')
            self.messageChanged.emit()
            return False
        self._message = ''
        self.changed.emit()
        self.messageChanged.emit()
        return True

    def record(self, paths, directory):
        """Paths and directory were canonicalized by the successful scan worker."""
        if not paths:
            return False
        seen, items = set(), []
        for path in [*paths, *self._store.items]:
            key = path_key(path)
            if key not in seen:
                seen.add(key)
                items.append(path)
        return self._commit(items[:MAX_RECENT_PATHS], directory)

    @Slot(str, result=bool)
    def remove(self, path):
        items = self.items
        if path not in items:
            return False
        items.remove(path)
        return self._commit(items, self.last_directory)

    @Slot(result=bool)
    def clear(self):
        return self._commit([], '')
