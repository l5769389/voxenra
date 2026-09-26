"""Render frozen measurement sources without driving any on-screen viewport."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
import numpy as np
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.ui.measurement_source import restore_request, frame_identity


def render_references(pictures, catalog, cancelled, progress):
    from qt_dicom_viewer.core.volume_manager import VolumeManager
    from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
    renderer = DicomRenderWorker(catalog, VolumeManager(maximum_cache_bytes=256*1024**2))
    received, errors, output, warnings = [], [], [], []
    renderer.render_finished.connect(received.append, Qt.DirectConnection)
    renderer.render_failed.connect(errors.append, Qt.DirectConnection)
    for index, picture in enumerate(pictures):
        if cancelled.is_set():
            raise InterruptedError()
        received.clear()
        errors.clear()
        try:
            request = restore_request(picture["source"], "report", display=picture["display"], cancel_event=cancelled)
            renderer.handleRenderRequest(request)
            if cancelled.is_set():
                raise InterruptedError()
            if errors:
                raise ValueError(errors[0].error)
            if not received:
                raise ValueError(_msg("report.imageUnavailable"))
            result = received[0]
            actual = frame_identity(result.series_uid, result.frame_meta,
                getattr(result, "projection_mode", None), getattr(result, "slab_thickness_mm", 0.),
                phase=getattr(result, "phase_identifier", None))
            if actual != picture["frame"]:
                raise ValueError(_msg("analysis.sourceMismatch"))
            if picture["source"].get("pixelFingerprint"):
                import hashlib
                actual_hash = hashlib.blake2b(np.ascontiguousarray(result.modality_pixel).view(np.uint8), digest_size=16).hexdigest()
                if actual_hash != picture["source"]["pixelFingerprint"]:
                    raise ValueError(_msg("analysis.sourceMismatch"))
            array = np.ascontiguousarray(result.image, dtype=np.uint8)
            channels = 1 if array.ndim == 2 else array.shape[2]
            fmt = {1: QImage.Format_Grayscale8, 3: QImage.Format_RGB888, 4: QImage.Format_RGBA8888}[channels]
            image = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], fmt).copy()
            output.append((picture["caption"], image, picture["measurements"], result.frame_meta.geometry.pixel_spacing))
        except InterruptedError:
            raise
        except Exception as exc:
            reason = _msg("report.imageUnavailable") + ": " + error_message(exc)
            warnings.append(reason)
            for row in picture["rows"]:
                row["reference_status"] = reason
        progress((index+1)/max(1, len(pictures)))
    return output, warnings
