"""Serialize thumbnail decoding away from the GUI and coalesce scan updates."""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage

from voxplane.core.series_thumbnail import read_series_thumbnail


@dataclass(frozen=True)
class ThumbnailRequest:
    series_uid: str
    path: Path
    frame_index: int | None = None


class _ThumbnailJob(QRunnable):
    def __init__(self, request, reader, completed):
        super().__init__()
        self.request, self.reader, self.completed = request, reader, completed

    def run(self):
        try:
            image = (self.reader(self.request.path) if self.request.frame_index is None
                     else self.reader(self.request.path, self.request.frame_index))
        except Exception:
            image = QImage()  # Unsupported codecs/non-image objects retain a modality placeholder.
        self.completed.emit(self.request, image)


class ThumbnailService(QObject):
    finished = Signal(object, object)
    _completed = Signal(object, object)

    def __init__(self, parent=None, *, reader=read_series_thumbnail):
        super().__init__(parent)
        self._reader = reader
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._pending = OrderedDict()
        self._latest = {}
        self._busy = False
        self._stopped = False
        self._completed.connect(self._complete)

    def submit(self, request: ThumbnailRequest):
        if self._stopped or self._latest.get(request.series_uid) == request:
            return
        self._latest[request.series_uid] = request
        self._pending[request.series_uid] = request
        self._pump()

    def cancel(self, series_uid: str):
        """Discard queued and in-flight results for one series."""
        self._pending.pop(series_uid, None)
        self._latest.pop(series_uid, None)

    def _pump(self):
        if self._stopped or self._busy or not self._pending:
            return
        _, request = self._pending.popitem(last=False)
        self._busy = True
        self._pool.start(_ThumbnailJob(request, self._reader, self._completed))

    @Slot(object, object)
    def _complete(self, request, image):
        self._busy = False
        if not self._stopped and self._latest.get(request.series_uid) == request:
            self.finished.emit(request, image)
        self._pump()

    def shutdown(self):
        self._stopped = True
        self._pending.clear()
        self._latest.clear()
        self._pool.waitForDone()
