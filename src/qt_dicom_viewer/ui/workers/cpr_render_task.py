"""Immutable CPR requests with one active/one newest pending job per workspace.

All CPR queues share one compute thread. Volumes arrive from the existing volume
owner and are only read here; this worker never touches the volume-manager LRU.
"""
from dataclasses import dataclass, replace
from threading import Event

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from qt_dicom_viewer.core.cpr_reslicer import CprReslicer
from qt_dicom_viewer.core.cpr_session import volume_content_fingerprint
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.render_cancellation import check_render_cancelled, render_cancellation
from qt_dicom_viewer.model import MprPlane
from qt_dicom_viewer.model.cpr import CprPath, CprSettings, CprResult, CprCrossSection, readonly_array
from qt_dicom_viewer.model.dicom_core import DicomVolume, MprFrame, MprSlice, Vector3


@dataclass(frozen=True, slots=True)
class CprCurveCache:
    volume: DicomVolume
    path: CprPath
    result: CprResult


@dataclass(frozen=True, slots=True)
class CprRenderInput:
    generation: int
    volume: DicomVolume
    path: CprPath | None
    settings: CprSettings
    position_mm: float
    reference_planes: tuple[MprPlane, MprPlane]
    reference_centers: tuple[Vector3, Vector3] | None = None
    cross_width_mm: float = 40.
    preview: bool = False
    cache: CprCurveCache | None = None
    source_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class CprRenderOutput:
    generation: int
    references: tuple[MprSlice, MprSlice]
    curve: CprResult | None
    section: CprCrossSection | None
    preview: bool
    cache: CprCurveCache | None
    source_fingerprint: str


def compute_cpr(request: CprRenderInput) -> CprRenderOutput:
    check_render_cancelled()
    volume, references = request.volume, []
    fingerprint = request.source_fingerprint or volume_content_fingerprint(volume)
    centers = request.reference_centers or (volume.geometry.center_patient,) * 2
    mpr = MprReslicer(max_output_dimension=512 if request.preview else 1024)
    for plane, position in zip(request.reference_planes, centers):
        # Keep the reference image's in-plane field stationary while navigating.
        center = list(volume.geometry.center_patient)
        axis = {MprPlane.AXIAL: 2, MprPlane.CORONAL: 1, MprPlane.SAGITTAL: 0}[plane]
        center[axis] = position[axis]
        result = mpr.reslice(volume, plane, MprFrame.standard_lps(tuple(center)))
        references.append(replace(result, modality_pixels=readonly_array(result.modality_pixels)))
        check_render_cancelled()
    curve, section, cache = None, None, None
    if request.path is not None:
        settings = request.settings
        if request.preview:
            settings = replace(settings, step_mm=min(10., max(1., settings.step_mm * 3)))
        cached = request.cache
        if (cached is not None and cached.volume is volume and cached.path == request.path
                and cached.result.settings == settings):
            curve = cached.result
        else:
            curve = replace(CprReslicer().reslice(volume, request.path, settings), source_fingerprint=fingerprint)
        index = int(np.argmin(np.abs(curve.centerline.distances_mm - request.position_mm)))
        section = CprReslicer().cross_section(volume, curve.centerline, index,
                    width_mm=request.cross_width_mm, step_mm=settings.step_mm)
        section = replace(section, source_fingerprint=fingerprint)
        cache = CprCurveCache(volume, request.path, curve)
    check_render_cancelled()
    return CprRenderOutput(request.generation, tuple(references), curve, section, request.preview, cache, fingerprint)


_pool = None


def _compute_pool():
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(1)
    return _pool


class _Signals(QObject):
    done = Signal(object, object, object)


class _Job(QRunnable):
    def __init__(self, request, compute):
        super().__init__()
        self.request, self.compute = request, compute
        self.cancel = Event()
        self.signals = _Signals()

    def run(self):
        result, error = None, None
        try:
            with render_cancellation(self.cancel):
                check_render_cancelled()
                result = self.compute(self.request)
                check_render_cancelled()
        except Exception as exc:
            error = exc
        self.signals.done.emit(self, result, error)


class CprRenderQueue(QObject):
    finished = Signal(object)
    failed = Signal(int, str)
    busyChanged = Signal()

    def __init__(self, parent=None, *, compute=compute_cpr):
        super().__init__(parent)
        self._compute = compute
        self._active = self._pending = None
        self._expected = None
        self._closed = False

    @property
    def running(self):
        return self._active is not None

    def submit(self, request: CprRenderInput):
        if self._closed:
            raise RuntimeError("CPR queue is closed")
        self._expected = request.generation
        if self._active is not None:
            self._active.cancel.set()
            self._pending = request
        else:
            self._start(request)

    def _start(self, request):
        job = _Job(request, self._compute)
        job.signals.done.connect(self._done)
        self._active = job
        _compute_pool().start(job)
        self.busyChanged.emit()

    def cancel(self):
        self._expected = self._pending = None
        if self._active is not None:
            self._active.cancel.set()

    def close(self):
        self._closed = True
        self.cancel()

    @Slot(object, object, object)
    def _done(self, job, result, error):
        if job is not self._active:
            return
        self._active = None
        pending, self._pending = self._pending, None
        if pending is not None and not self._closed:
            self._start(pending)
            return
        self.busyChanged.emit()
        if self._closed or job.cancel.is_set() or job.request.generation != self._expected:
            return
        if error is None:
            self.finished.emit(result)
        elif not isinstance(error, InterruptedError):
            self.failed.emit(job.request.generation, str(error))
