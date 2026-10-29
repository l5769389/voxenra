"""Favorite directory actions share the panel's existing import pipeline."""
import os
import queue
import threading
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property
from qt_dicom_viewer.settings.favorite_directories import FavoriteDirectoriesStore, MAX_FAVORITES, path_key


class FavoriteDirectoriesController(QObject):
    changed = Signal()
    busyChanged = Signal()
    messageChanged = Signal()
    _i18n_message = Signal()

    def __init__(self, panel, path=None):
        super().__init__(panel)
        self._panel = panel
        self._store = FavoriteDirectoriesStore(path)
        self._message = ''
        self._is_error = False
        self._validation_results = queue.SimpleQueue()
        self._validation_serial = 0
        self._pending_validation = None
        self._validation_timer = QTimer(self)
        self._validation_timer.setInterval(20)
        self._validation_timer.timeout.connect(self._finish_validation)

    @Property('QVariantList', notify=changed)
    def items(self):
        return [dict(item) for item in self._store.items]

    @translated_property(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='messageChanged')
    def message(self):
        return self._message

    @Property(bool, notify=messageChanged)
    def isError(self):
        return self._is_error

    def _feedback(self, message='', error=False):
        self._message, self._is_error = message, error
        self.messageChanged.emit()
        if error:
            self._panel._set_status(message, True)
        return not error

    def _error(self, key, **kwargs):
        return self._feedback(_msg('favorites.' + key, **kwargs), True)

    def _commit(self, items):
        try:
            self._store.save(items)
        except OSError:
            return self._error('saveFailed')
        self.changed.emit()
        return self._feedback()

    def _index(self, identifier):
        for index, item in enumerate(self._store.items):
            if item['id'] == identifier:
                return index
        self._error('notFound')
        return None

    @staticmethod
    def _checked_directory(value):
        try:
            if not value.strip() or '\0' in value:
                raise ValueError('Invalid directory')
            folder = Path(value).expanduser().resolve(strict=True)
            if not folder.is_dir() or not os.access(folder, os.R_OK | os.X_OK):
                raise OSError('Unreadable directory')
            # Opening scandir verifies listing permission without scanning its contents.
            with os.scandir(folder):
                pass
            return str(folder)
        except (OSError, ValueError, RuntimeError):
            return None

    def _directory(self, value):
        folder = self._checked_directory(value)
        if folder is None:
            self._error('unavailable', path=value)
        return folder

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._pending_validation is not None

    @Slot(str, result=bool)
    def requestAdd(self, path):
        return self._request_validation(path)

    @Slot(str, str, result=bool)
    def requestReplacement(self, identifier, path):
        if self._index(identifier) is None:
            return False
        return self._request_validation(path, identifier)

    def _request_validation(self, path, identifier=''):
        if self.busy or self._panel._closing:
            return False
        if not identifier and len(self._store.items) >= MAX_FAVORITES:
            return self._error('limit', count=MAX_FAVORITES)
        self._validation_serial += 1
        serial = self._validation_serial
        self._pending_validation = (serial, identifier, path)
        results = self._validation_results
        check = self._checked_directory
        # The worker captures no QObject. Closing/deleting the UI never waits
        # for an unavailable volume and a late result cannot call into Qt.
        def worker():
            try:
                folder = check(path)
            except Exception:
                folder = None
            results.put((serial, folder))
        self.busyChanged.emit()
        self._feedback(_msg('favorites.checking'))
        self._validation_timer.start()
        threading.Thread(target=worker, daemon=True).start()
        return True

    @Slot()
    def cancelValidation(self):
        if self._pending_validation is not None:
            self._pending_validation = None
            self._validation_timer.stop()
            self.busyChanged.emit()
            self._feedback()

    def _finish_validation(self):
        while True:
            try:
                serial, folder = self._validation_results.get_nowait()
            except queue.Empty:
                return
            pending = self._pending_validation
            if pending is None or pending[0] != serial:
                continue
            self._pending_validation = None
            self._validation_timer.stop()
            _, identifier, path = pending
            try:
                if self._panel._closing:
                    self._feedback()
                elif folder is None:
                    self._error('unavailable', path=path)
                elif identifier:
                    self._replace_checked(identifier, folder)
                else:
                    self._add_checked(folder)
            finally:
                self.busyChanged.emit()
            return

    def _duplicate(self, folder, except_id=''):
        return any(item['id'] != except_id and path_key(item['path']) == path_key(folder)
                   for item in self._store.items)

    @Slot(str, result=bool)
    def add(self, path):
        if len(self._store.items) >= MAX_FAVORITES:
            return self._error('limit', count=MAX_FAVORITES)
        folder = self._directory(path)
        if folder is None:
            return False
        return self._add_checked(folder)

    def _add_checked(self, folder):
        if len(self._store.items) >= MAX_FAVORITES:
            return self._error('limit', count=MAX_FAVORITES)
        if self._duplicate(folder):
            return self._error('duplicate')
        return self._commit(self.items + [dict(id=uuid4().hex, name=Path(folder).name or folder, path=folder)])

    @Slot(str, str, result=bool)
    def rename(self, identifier, name):
        index = self._index(identifier)
        if index is None:
            return False
        name = name.strip()
        if not name or len(name) > 120 or '\0' in name:
            return self._error('invalidName')
        items = self.items
        items[index]['name'] = name
        return self._commit(items)

    @Slot(str, int, result=bool)
    def move(self, identifier, offset):
        index = self._index(identifier)
        if index is None:
            return False
        target = index + offset
        if not 0 <= target < len(self._store.items):
            return False
        items = self.items
        items.insert(target, items.pop(index))
        return self._commit(items)

    @Slot(str, result=bool)
    def remove(self, identifier):
        index = self._index(identifier)
        if index is None:
            return False
        items = self.items
        items.pop(index)
        return self._commit(items)

    @Slot(str, str, result=bool)
    def replace(self, identifier, path):
        index = self._index(identifier)
        if index is None:
            return False
        folder = self._directory(path)
        if folder is None:
            return False
        return self._replace_checked(identifier, folder)

    def _replace_checked(self, identifier, folder):
        index = self._index(identifier)
        if index is None:
            return False
        if self._duplicate(folder, identifier):
            return self._error('duplicate')
        items = self.items
        items[index]['path'] = folder
        return self._commit(items)

    def _can_import(self):
        panel = self._panel
        if panel._closing or panel._scanning:
            return self._error('busy')
        reason = panel._import_blocker()
        if not reason and panel._workspace_is_restoring():
            reason = _msg('import.waitForWorkspace')
        if reason:
            return self._feedback(reason, True)
        return True

    @Slot(str, result=bool)
    def importFavorite(self, identifier):
        if not self._can_import():
            return False
        index = self._index(identifier)
        if index is None:
            return False
        folder = self._directory(self._store.items[index]['path'])
        if folder is None:
            return False
        if self._panel._start_import([folder]):
            self._panel._last_import_directory = folder
            return self._feedback()
        return self._error('busy')

    @Slot()
    def chooseAndAdd(self):
        from qt_dicom_viewer.ui.dialogs.favorite_directories_dialog import choose_favorite_directory
        choose_favorite_directory(self)

    @Slot(str)
    def chooseReplacement(self, identifier):
        if self._index(identifier) is None:
            return
        from qt_dicom_viewer.ui.dialogs.favorite_directories_dialog import choose_favorite_directory
        choose_favorite_directory(self, identifier)

    @Slot()
    def showManager(self):
        from qt_dicom_viewer.ui.dialogs.favorite_directories_dialog import show_favorite_directories
        show_favorite_directories(self)
