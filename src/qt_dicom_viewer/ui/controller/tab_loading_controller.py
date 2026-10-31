"""Opening state only: ordinary slice/window updates keep the image interactive."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from PySide6.QtCore import QObject, Property, Signal, Slot


class TabLoadingController(QObject):
    _i18n_errorMessage = Signal()
    _i18n_message = Signal()
    changed = Signal()

    def __init__(self, tab):
        super().__init__(tab)
        self._expected = set(tab.viewports_by_id)
        self._completed = set()
        self._pending = {}
        self._closed = False
        self._status = "loading"
        self._error = ""
        self._tag = tab.tagController
        self._volumes = [v for v in tab.viewports_by_id.values() if v.viewportType == "volume"]
        for viewport in self._volumes:
            viewport.loadStateChanged.connect(self.sync_volume)
        if self._tag is not None:
            self._tag.stateChanged.connect(self.sync_tag)

    @Property(bool, notify=changed)
    def loading(self):
        return self._status == "loading"

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @_TextProperty(str, notify=_i18n_errorMessage, notify_name='_i18n_errorMessage', source_notify='changed')
    def errorMessage(self):
        return self._error

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='changed')
    def message(self):
        if self._error:
            return self._error
        if self._tag is not None:
            return _msg('text.0437')
        if self._completed and len(self._expected) > 1:
            return _msg('text.0438', value1=len(self._completed), value2=len(self._expected))
        return _msg('text.0439')

    def finish(self):
        tab = self.parent()
        if hasattr(tab, "cprLoaded") and tab.hasError:
            self._status, self._error = "error", tab.message
        else:
            self._status, self._error = "ready", ""
        self._pending.clear()
        self.changed.emit()

    @Slot()
    def sync_volume(self):
        if self._closed:
            return
        for viewport in self._volumes:
            if viewport.loadState == "loading" and self._status == "ready":
                self.restart()
            if viewport.loadState == "error":
                self._status, self._error = "error", viewport._error
                self.changed.emit()
                return

    def restart(self):
        self._status, self._error = "loading", ""
        self._completed.clear()
        self.changed.emit()

    @Slot(object)
    def observe_request(self, request):
        if not self._closed and self._status != "ready":
            self._pending[request.viewport_id] = request.request_id

    def accept_result(self, result):
        if (self._closed or not self.loading
                or self._pending.get(result.viewport_id) != result.response_id):
            return
        frames = getattr(result, "frames", (result,))
        self._completed.update(frame.viewport_id for frame in frames)
        if self._expected <= self._completed:
            self._status = "ready"
            self._pending.clear()
        self.changed.emit()

    def accept_failure(self, failure):
        if (not self._closed and self.loading
                and self._pending.get(failure.viewport_id) == failure.request_id):
            self._status = "error"
            self._error = error_message(failure.error) or _msg('text.0440')
            self.changed.emit()

    @Slot()
    def sync_tag(self):
        if self._closed or self._status == "ready" or self._tag.loading:
            return
        self._error = self._tag._error
        self._status = "error" if self._error else "ready"
        self.changed.emit()

    def close(self):
        self._closed = True
        self._pending.clear()
