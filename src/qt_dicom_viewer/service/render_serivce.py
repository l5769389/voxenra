import logging
from dataclasses import replace
from threading import Event
from PySide6.QtCore import (
    QObject,
    QThread,
    Signal,
    Slot,
)

from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import RenderRequest, RenderResult
from qt_dicom_viewer.model.render_models import PetBatchRenderRequest, PetBatchRenderResult
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker



logger = logging.getLogger(__name__)

class RenderService(QObject):
    renderRequested = Signal(object)
    rendered = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        series_catalog: SeriesCatalog,
        volume_manager: VolumeManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        logger.info("Starting render service")

        self._thread = QThread(self)

        # Worker 不能设置 parent，因为稍后需要 moveToThread()
        self._worker = DicomRenderWorker(
            series_catalog,
            volume_manager
        )
        self._worker.moveToThread(self._thread)
        self._active = {}
        self._pending = {}
        self._active_requests = {}
        self._closing = False

        self.renderRequested.connect(self._worker.handleRenderRequest)

        # 转发 Worker 的结果
        self._worker.render_finished.connect(self.handleRenderFinished)
        self._worker.render_failed.connect(self.handleRenderFailed)

        self._thread.finished.connect(
            self._worker.deleteLater
        )

        self._thread.start()

    @Slot(object)
    def handleRenderFinished(self, result: RenderResult) -> None:
        key = result.viewport_id
        if self._active.get(key) != result.response_id:
            return
        self._active.pop(key, None)
        completed = self._active_requests.pop(key, None)
        cancelled = completed is not None and completed.cancel_event.is_set()
        pending = self._pending.pop(key, None)
        # Present completed interactive frames while the newest transform is
        # queued. The owner still rejects other interactions / stale settings.
        interactive = (isinstance(result, PetBatchRenderResult)
                       and result.request is not None
                       and (result.request.preview or result.request.interaction_kind == "locator"))
        if not self._closing and not cancelled and (pending is None or interactive):
            self.rendered.emit(result)
        if pending is not None and not self._closing:
            self.submit(pending)

    @Slot(object)
    def handleRenderFailed(self, failure):
        key = failure.viewport_id
        if self._active.get(key) != failure.request_id:
            return
        self._active.pop(key, None)
        completed = self._active_requests.pop(key, None)
        cancelled = completed is not None and completed.cancel_event.is_set()
        pending = self._pending.pop(key, None)
        if not self._closing and not cancelled and pending is None:
            self.failed.emit(failure)
        if pending is not None and not self._closing:
            self.submit(pending)

    @Slot(object)
    def submit(self, request: RenderRequest) -> None:
        if self._closing:
            return
        if request.viewport_id in self._active:
            self._pending[request.viewport_id] = request
            active = self._active_requests.get(request.viewport_id)
            if (isinstance(active, PetBatchRenderRequest) and not active.preview
                    and isinstance(request, PetBatchRenderRequest) and request.preview):
                # A new gesture should not wait behind the previous full MIP.
                # Never cancel a running preview just because movement continues.
                active.cancel_event.set()
            return
        request = replace(request, cancel_event=Event())
        self._active_requests[request.viewport_id] = request
        self._active[request.viewport_id] = request.request_id
        logger.info(f"Submitting render request: {request.request_id}")
        self.renderRequested.emit(request)

    @Slot(object)
    def cancel(self, viewport_ids):
        """Drop queued work and stop a running volume build between source frames."""
        for key in viewport_ids:
            self._pending.pop(key, None)
            request = self._active_requests.get(key)
            if request is not None:
                request.cancel_event.set()

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        self._pending.clear()
        for request in self._active_requests.values():
            request.cancel_event.set()
        if not self._thread.isRunning():
            return
        logger.info("Stopping render service")
        self._thread.quit()
        self._thread.wait()

        logger.info("Render service stopped")
