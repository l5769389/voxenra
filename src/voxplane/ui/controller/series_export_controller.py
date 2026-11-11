"""Own the export dialog and one cancellable background export at a time."""
from voxplane.i18n.messages import error_message
from voxplane.i18n import message as _msg
from voxplane.i18n.qt import translated_property as _TextProperty

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot

from voxplane.core.series_export import ExportCancelled, ExportError, ExportRequest, export_series
from voxplane.ui.file_location import reveal_path


class _ExportJob(QRunnable):
    def __init__(self, request, cancel, progress, completed):
        super().__init__()
        self.request, self.cancel = request, cancel
        self.progress, self.completed = progress, completed

    def run(self):
        try:
            result = export_series(self.request, cancel=self.cancel, progress=self.progress.emit)
            self.completed.emit(result, "")
        except ExportCancelled:
            self.completed.emit(None, _msg('text.0441'))
        except ExportError as exc:
            self.completed.emit(None, error_message(exc))
        except Exception:
            self.completed.emit(None, _msg('text.0442'))


class SeriesExportController(QObject):
    _i18n_message = Signal()
    changed = Signal()
    dialogChanged = Signal()
    _progress = Signal(int, int)
    _completed = Signal(object, object)

    def __init__(self, catalog, settings, parent=None):
        super().__init__(parent)
        self._catalog, self._settings = catalog, settings
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cancel = Event()
        self._closing = False
        self._busy = False
        self._open = False
        self._locked = False
        self._series_uid = ""
        self._count = 0
        self._done = self._total = 0
        self._message = self._output = ""
        self._progress.connect(self._on_progress)
        self._completed.connect(self._on_completed)

    @Property(bool, notify=dialogChanged)
    def dialogOpen(self):
        return self._open

    @Property(bool, notify=dialogChanged)
    def anonymousLocked(self):
        return self._locked

    @Property(bool, notify=dialogChanged)
    def containsFrameGroups(self):
        series = self._catalog.get_series(self._series_uid)
        return bool(series and any(i.frame_index is not None for i in series.instances))

    @Property(int, notify=dialogChanged)
    def instanceCount(self):
        return self._count

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='changed')
    def message(self):
        return self._message

    @Property(str, notify=changed)
    def outputDirectory(self):
        return self._output

    @Property(int, notify=changed)
    def completedCount(self):
        return self._done

    @Property(int, notify=changed)
    def totalCount(self):
        return self._total

    @Slot(str, bool)
    def openSeries(self, uid, anonymous_locked=False):
        if self._busy or self._closing:
            return
        series = self._catalog.get_series(uid)
        self._series_uid = uid
        self._count = len(series.instances) if series else 0
        self._locked = anonymous_locked
        self._message = "" if self._count else _msg('text.0140')
        self._output = ""
        self._done = self._total = 0
        self._open = True
        self.dialogChanged.emit()
        self.changed.emit()

    @Slot()
    def closeDialog(self):
        if not self._busy:
            self._open = False
            self.dialogChanged.emit()

    @Slot(str, bool)
    def startExport(self, file_format, anonymous):
        if self._busy or self._closing or not self._open:
            return
        series = self._catalog.get_series(self._series_uid)
        if file_format not in ("png", "dicom") or not series or not series.instances:
            self._message = _msg('text.0443')
            self.changed.emit()
            return
        # Capture an immutable snapshot; subsequent imports/selections cannot
        # change the running export or accidentally export a different series.
        request = ExportRequest(tuple(instance.path for instance in series.instances),
                                Path(self._settings.exportDirectory), file_format,
                                self._locked or anonymous,
                                tuple((i.path, i.frame_index) for i in series.instances if i.frame_index is not None))
        self._cancel = Event()
        self._busy = True
        self._output = ""
        self._message = _msg('text.0444')
        self._done = self._total = 0
        self.changed.emit()
        self._pool.start(_ExportJob(request, self._cancel, self._progress, self._completed))

    @Slot()
    def cancelExport(self):
        if self._busy:
            self._cancel.set()
            self._message = _msg('text.0445')
            self.changed.emit()

    @Slot(int, int)
    def _on_progress(self, done, total):
        if self._closing:
            return
        self._done, self._total = done, total
        if not self._cancel.is_set():
            self._message = _msg('text.0446', value1=done, value2=total)
        self.changed.emit()

    @Slot(object, object)
    def _on_completed(self, result, error):
        self._busy = False
        if self._closing:
            return
        self._output = str(result.directory) if result else ""
        self._message = _msg('text.0447', value1=result.file_count) if result else error
        self.changed.emit()

    @Slot()
    def openOutputDirectory(self):
        if self._output and not reveal_path(self._output):
            self._message = _msg('text.0448')
            self.changed.emit()

    def shutdown(self):
        self._closing = True
        self._cancel.set()
        self._pool.waitForDone()
