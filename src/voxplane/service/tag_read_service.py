"""One background reader, with at most one pending request per open tag tab."""

from collections import OrderedDict

from PySide6.QtCore import QObject, QThread, Signal, Slot

from voxplane.core.dicom_tag_reader import read_dicom_tags
from voxplane.model.dicom_tags import TagReadRequest, TagReadResult


class _TagReadWorker(QObject):
    finished = Signal(object)

    def __init__(self, reader):
        super().__init__()
        self._reader = reader

    @Slot(object)
    def read(self, request: TagReadRequest) -> None:
        try:
            result = TagReadResult(request, self._reader(request.path))
        except Exception as error:
            result = TagReadResult(request, error=f"{type(error).__name__}: {error}")
        self.finished.emit(result)


class TagReadService(QObject):
    finished = Signal(object)
    _readRequested = Signal(object)

    def __init__(self, parent=None, *, reader=read_dicom_tags):
        super().__init__(parent)
        self._reader = reader
        self._thread = None
        self._worker = None
        self._pending: OrderedDict[str, TagReadRequest] = OrderedDict()
        self._latest: dict[str, str] = {}
        self._inflight: TagReadRequest | None = None
        self._stopped = False

    def submit(self, request: TagReadRequest) -> None:
        if self._stopped:
            return
        self._latest[request.tab_id] = request.request_id
        self._pending[request.tab_id] = request
        self._pump()

    def cancel(self, tab_id: str) -> None:
        self._pending.pop(tab_id, None)
        self._latest.pop(tab_id, None)

    def _pump(self) -> None:
        if self._stopped or self._inflight is not None or not self._pending:
            return
        if self._thread is None:
            self._thread = QThread(self)
            self._worker = _TagReadWorker(self._reader)
            self._worker.moveToThread(self._thread)
            self._readRequested.connect(self._worker.read)
            self._worker.finished.connect(self._complete)
            self._thread.finished.connect(self._worker.deleteLater)
            self._thread.start()
        _, self._inflight = self._pending.popitem(last=False)
        self._readRequested.emit(self._inflight)

    @Slot(object)
    def _complete(self, result: TagReadResult) -> None:
        self._inflight = None
        if not self._stopped and self._latest.get(result.request.tab_id) == result.request.request_id:
            self.finished.emit(result)
        self._pump()

    @Slot()
    def shutdown(self) -> None:
        self._stopped = True
        self._pending.clear()
        self._latest.clear()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
