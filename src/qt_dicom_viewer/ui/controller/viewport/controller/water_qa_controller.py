"""Per-viewport water QA, asynchronous snapshots and bounded per-slice caching."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.ui.controller.settings_controller import resolve_settings
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from collections import OrderedDict
from dataclasses import asdict, replace
import hashlib
import math

import numpy as np
from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Qt, Signal, Slot

from qt_dicom_viewer.core.water_qa import analyze_water_phantom, measure_water_phantom
from qt_dicom_viewer.model.water_qa import WaterQaSettings


class _Signals(QObject):
    completed = Signal(int, object, object, object)


class _QaTask(QRunnable):
    def __init__(self, token, key, pixels, spacing, settings, previous=None):
        super().__init__()
        self.token, self.key = token, key
        self.pixels, self.spacing, self.settings = pixels, spacing, settings
        self.previous = previous
        self.signals = _Signals()

    def run(self):
        try:
            result = (measure_water_phantom(self.pixels, self.spacing, self.previous.phantom,
                self.settings, centers=[(r.column, r.row) for r in self.previous.rois[:5]],
                extra_rois=self.previous.rois[5:]) if self.previous is not None and self.previous.settings == self.settings else
                analyze_water_phantom(self.pixels, self.spacing, self.settings))
        except Exception as exc:
            self.signals.completed.emit(self.token, self.key, None, error_message(exc) or _msg('text.0591'))
        else:
            self.signals.completed.emit(self.token, self.key, result, "")


class WaterQaController(QObject):
    recordsChanged = Signal()
    _i18n_provenance = Signal()
    _i18n_currentResult = Signal()
    _i18n_error = Signal()
    _i18n_roiItems = Signal()
    _i18n_statusText = Signal()
    stateChanged = Signal()
    settingsChanged = Signal()

    def __init__(self, modality, parent=None):
        super().__init__(parent)
        self._settings_controller = resolve_settings(parent)
        self._modality = modality.strip().upper()
        self._settings = WaterQaSettings()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._tasks = {}
        self._pending = None
        self._cache = OrderedDict()
        self._records = {}
        self._restored = False
        self._token = 0
        self._closed = False
        self._enabled = False
        self._frame = self._pixels = self._key = None
        self._status, self._error, self._result = "empty", "", None
        self._drag = self._draft_centers = None
        self._hover_key = ""
        self._selected_key = ""

    def _remember_result(self):
        if self._result is None or self._key is None:
            return
        from datetime import datetime, timezone
        from qt_dicom_viewer import __version__
        self._records[repr(self._key)] = dict(key=self._key, result=self._result,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"), algorithm="1", app=__version__)
        self.recordsChanged.emit()

    @_TextProperty(str, notify=_i18n_provenance, notify_name="_i18n_provenance", source_notify="stateChanged")
    def provenance(self):
        record = self._records.get(repr(self._key))
        return (_msg("analysis.provenance", value1=record["app"], value2=record["algorithm"], value3=record["timestamp"])
                if record else "")

    def persistent_state(self):
        return dict(version=1, enabled=self._enabled, settings=self._settings,
                    records=list(self._records.values()))

    def restore_state(self, state):
        if not state or state.get("version") != 1:
            return
        self._invalidate()
        self._cache.clear()
        self._restored = bool(state.get("records") or state.get("enabled", False))
        self._enabled = state.get("enabled", False)
        self._settings = state.get("settings", WaterQaSettings())
        self._records = {repr(r["key"]): r for r in state.get("records", [])}
        self._restore_current_record()
        self.settingsChanged.emit()
        self.stateChanged.emit()

    def _restore_current_record(self):
        """Apply the same identity check on reopening and on frame navigation."""
        if self._key is None:
            return False
        saved = self._records.get(repr(self._key))
        if saved:
            self._result, self._settings = saved["result"], saved["result"].settings
            self._status, self._error = "ready", ""
            return True
        if self._restored:
            self._result = None
            self._status, self._error = "empty", ""
            if any(tuple(r["key"][:3]) == self._key[:3] for r in self._records.values()):
                self._status, self._error = "error", _msg("analysis.sourceMismatch")
            return True
        return False

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    @Property(bool, constant=True)
    def available(self):
        return self._modality == "CT"

    @Property(bool, notify=stateChanged)
    def enabled(self):
        return self._enabled

    @Property(str, notify=stateChanged)
    def status(self):
        return self._status

    @_TextProperty(str, notify=_i18n_statusText, notify_name='_i18n_statusText', source_notify='stateChanged')
    def statusText(self):
        if not self.available:
            return _msg('text.0592')
        return {"empty": _msg('text.0593'), "waiting": _msg('text.0594'),
                "calculating": _msg('text.0595'), "error": "",
                "ready": _msg('text.0596') if self.dragging else ""}[self._status]

    @Property(bool, notify=stateChanged)
    def dragging(self):
        return self._drag is not None

    @Property(str, notify=stateChanged)
    def hoverCursorKind(self):
        return "pan" if self._hover_key else ""

    @_TextProperty(str, notify=_i18n_error, notify_name='_i18n_error', source_notify='stateChanged')
    def error(self):
        return self._error

    @Property(float, notify=settingsChanged)
    def roiDiameterMm(self):
        return self._settings.roi_diameter_mm

    @Property(float, notify=settingsChanged)
    def edgeClearanceMm(self):
        return self._settings.edge_clearance_mm

    @_TextProperty('QVariantMap', notify=_i18n_currentResult, notify_name='_i18n_currentResult', source_notify='stateChanged')
    def currentResult(self):
        if self._result is None or self._status != "ready":
            return {}
        result = asdict(self._result)
        result["rois"] = [dict(asdict(roi), removable=roi.key.startswith("extra-")) for roi in self._result.rois]
        return result

    @_TextProperty('QVariantList', notify=_i18n_roiItems, notify_name='_i18n_roiItems', source_notify='stateChanged')
    def roiItems(self):
        if self._result is None or self._frame is None or self._status != "ready":
            return []
        row_spacing, column_spacing = self._frame.instance_meta.pixel_spacing
        colors = ("#f6bf66", "#41cce5", "#41cce5", "#8de1b1", "#8de1b1")
        colors += ("#c4a7ff",) * max(0, len(self._result.rois)-5)
        centers = self._draft_centers or [(r.column, r.row) for r in self._result.rois]
        return [dict(key=r.key, label=r.label, column=center[0], row=center[1],
                     radiusColumn=r.radius_mm/column_spacing, radiusRow=r.radius_mm/row_spacing,
                     meanHu=r.mean_hu, stdHu=r.std_hu, color=color,
                     editing=self._drag is not None and self._drag[0] == index,
                     hovered=r.key == self._hover_key, selected=r.key == self._selected_key,
                     removable=r.key.startswith("extra-"))
                for index, (r, color, center) in enumerate(zip(self._result.rois, colors, centers))]

    def _hit_roi(self, column, row):
        if (not self._enabled or self._status != "ready" or self._result is None
                or not math.isfinite(column) or not math.isfinite(row)):
            return None
        sy, sx = self._frame.instance_meta.pixel_spacing
        for index in reversed(range(len(self._result.rois))):
            roi = self._result.rois[index]
            if math.hypot((column-roi.column)*sx, (row-roi.row)*sy) <= roi.radius_mm:
                return index
        return None

    def update_hover(self, column, row):
        if self.dragging:
            return
        index = self._hit_roi(column, row)
        key = "" if index is None else self._result.rois[index].key
        if key != self._hover_key:
            self._hover_key = key
            self.stateChanged.emit()

    @Slot()
    def clearHover(self):
        if self._hover_key:
            self._hover_key = ""
            self.stateChanged.emit()

    def begin_drag(self, column, row):
        self.cancel_drag()
        index = self._hit_roi(column, row)
        if index is None:
            return
        self._selected_key = self._result.rois[index].key
        self._drag = (index, column, row)
        self._draft_centers = [(r.column, r.row) for r in self._result.rois]
        self._error = ""
        self.stateChanged.emit()

    def update_drag(self, column, row):
        if not self.dragging or not math.isfinite(column) or not math.isfinite(row):
            return
        index, start_column, start_row = self._drag
        roi, phantom = self._result.rois[index], self._result.phantom
        sy, sx = self._frame.instance_meta.pixel_spacing
        dx = (roi.column+column-start_column-phantom.column)*sx
        dy = (roi.row+row-start_row-phantom.row)*sy
        distance = math.hypot(dx, dy)
        # Constrain the complete circle to the detected water region. Pointer
        # displacement remains relative to the press, so the ROI never jumps.
        scale = min(1.0, (phantom.radius_mm-roi.radius_mm)/max(distance, 1e-9))
        center = (phantom.column+dx*scale/sx, phantom.row+dy*scale/sy)
        if center != self._draft_centers[index]:
            self._draft_centers[index] = center
            self.stateChanged.emit()

    def end_drag(self, column, row):
        if not self.dragging:
            return
        self.update_drag(column, row)
        centers = self._draft_centers
        self._drag = self._draft_centers = None
        try:
            result = measure_water_phantom(self._pixels, self._frame.instance_meta.pixel_spacing,
                                          self._result.phantom, self._settings, centers=centers[:5],
                                          extra_rois=tuple(replace(r, column=p[0], row=p[1])
                                              for r, p in zip(self._result.rois[5:], centers[5:])))
        except ValueError as exc:
            self._error = error_message(exc)  # Keep the last complete, valid measurement.
        else:
            self._result, self._error = result, ""
            self._cache[self._cache_key()] = (result, "")
            self._remember_result()
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def copyRoi(self, key):
        if self._closed or self._status != "ready" or self.dragging:
            return False
        source = next((r for r in self._result.rois if r.key == key), None)
        if source is None:
            return False
        number = 1 + max((int(r.key.split("-")[1]) for r in self._result.rois
                          if r.key.startswith("extra-")), default=0)
        sy, sx = self._frame.instance_meta.pixel_spacing
        phantom = self._result.phantom
        # Prefer a nearby free position; copied ROIs can still be moved
        # independently and may overlap when comparing the same region.
        center = (source.column, source.row)
        for angle in (45, 135, 225, 315, 0, 90, 180, 270):
            step = source.radius_mm * 2.2
            x = source.column + step*math.cos(math.radians(angle))/sx
            y = source.row + step*math.sin(math.radians(angle))/sy
            if (math.hypot((x-phantom.column)*sx, (y-phantom.row)*sy) + source.radius_mm <= phantom.radius_mm
                    and all(math.hypot((x-r.column)*sx, (y-r.row)*sy) >= source.radius_mm+r.radius_mm
                            for r in self._result.rois)):
                center = (x, y)
                break
        copy = replace(source, key=f"extra-{number}", label=f"ROI {number+5}",
                       column=center[0], row=center[1])
        try:
            result = measure_water_phantom(self._pixels, self._frame.instance_meta.pixel_spacing,
                phantom, self._settings, centers=[(r.column,r.row) for r in self._result.rois[:5]],
                extra_rois=self._result.rois[5:] + (copy,))
        except ValueError as exc:
            self._error = error_message(exc)
            self.stateChanged.emit()
            return False
        self._result, self._selected_key, self._error = result, copy.key, ""
        self._cache[self._cache_key()] = (result, "")
        self._remember_result()
        self.stateChanged.emit()
        return True

    @Slot(str, result=bool)
    def deleteRoi(self, key):
        if (self._closed or self._status != "ready" or self.dragging
                or not key.startswith("extra-") or not any(r.key == key for r in self._result.rois)):
            return False
        self._result = replace(self._result, rois=tuple(r for r in self._result.rois if r.key != key))
        self._selected_key = self._hover_key = self._error = ""
        self._cache[self._cache_key()] = (self._result, "")
        self._remember_result()
        self.stateChanged.emit()
        return True

    def delete_selected(self):
        self.deleteRoi(self._selected_key)

    def cancel_drag(self):
        if self.dragging:
            self._drag = self._draft_centers = None
            self.stateChanged.emit()

    def set_frame(self, series_uid, frame, pixels):
        if self._closed:
            return
        array = None if pixels is None else np.ascontiguousarray(pixels)
        fingerprint = None if array is None else hashlib.blake2b(array.view(np.uint8), digest_size=12).hexdigest()
        key = (series_uid, frame.instance_meta.sop_instance_uid, frame.slice_index,
               frame.instance_meta.pixel_spacing, None if array is None else array.shape, fingerprint,
               frame.geometry.image_position_patient, frame.geometry.image_orientation_patient, frame.instance_meta.frame_index)
        self._frame, self._pixels = frame, array
        if key == self._key:
            return  # Window/level and inversion do not alter the original HU data.
        self._invalidate()
        self._key = key
        if self._restore_current_record():
            self.settingsChanged.emit()
            self.stateChanged.emit()
        elif self._enabled:
            self._analyze()
        else:
            self.stateChanged.emit()

    def set_current_slice(self, index):
        if self._closed:
            return
        self._invalidate()
        self._frame = self._pixels = self._key = None
        self._status = "waiting" if self._enabled else "empty"
        self.stateChanged.emit()

    def _invalidate(self):
        self._token += 1
        self._pending = None
        self._drag = self._draft_centers = None
        self._hover_key = ""
        self._selected_key = ""
        self._status, self._error, self._result = "empty", "", None

    @Slot()
    def activate(self):
        if self._closed or not self.available:
            return
        self._enabled = True
        if self._status not in ("ready", "calculating") and not self._restored:
            self._analyze()

    @Slot()
    def analyze(self):
        if self._closed or not self.available:
            return
        self._enabled = True
        self._cache.pop(self._cache_key(), None)
        self._invalidate()
        self._analyze()

    def _cache_key(self):
        return self._key, self._settings

    def _analyze(self):
        if self._frame is None:
            self._status = "waiting"
            self.stateChanged.emit()
            return
        key = self._cache_key()
        cached = self._cache.get(key)
        if cached is not None:
            self._result, self._error = cached
            self._status = "error" if self._error else "ready"
            self._cache.move_to_end(key)
        elif self._pixels is None:
            self._status, self._error = "error", _msg('text.0597')
        else:
            self._status = "calculating"
            self._submit(self._token, key, self._pixels.copy(),
                         self._frame.instance_meta.pixel_spacing, self._settings)
        self.stateChanged.emit()

    def _submit(self, token, key, pixels, spacing, settings):
        # While scrolling, keep at most one running snapshot and the newest
        # pending slice. Never enqueue an entire series of obsolete analyses.
        if self._tasks:
            self._pending = (token, key, pixels, spacing, settings)
            return
        task = _QaTask(token, key, pixels, spacing, settings,
                       self._records.get(repr(key[0]), {}).get("result"))
        self._tasks[token] = task
        task.signals.completed.connect(self._receive_result, Qt.QueuedConnection)
        self._pool.start(task)

    @Slot(int, object, object, object)
    def _receive_result(self, token, key, result, error):
        self._tasks.pop(token, None)
        pending, self._pending = self._pending, None
        if pending is not None and not self._closed and pending[0] == self._token:
            self._submit(*pending)
        if self._closed or token != self._token or key != self._cache_key() or not self._enabled:
            return
        self._result, self._error = result, error
        self._status = "error" if error else "ready"
        self._cache[key] = (result, error)
        if result is not None and not error:
            self._remember_result()
        while len(self._cache) > 16:
            self._cache.popitem(last=False)
        self.stateChanged.emit()

    @Slot(float)
    def setRoiDiameterMm(self, value):
        self._set_setting("roi_diameter_mm", value, 2, 100)

    @Slot(float)
    def setEdgeClearanceMm(self, value):
        self._set_setting("edge_clearance_mm", value, 0, 100)

    def _set_setting(self, name, value, low, high):
        if self._closed or not math.isfinite(value) or not low <= value <= high:
            return
        settings = replace(self._settings, **{name: float(value)})
        if settings == self._settings:
            return
        self._settings = settings
        self.recordsChanged.emit()
        self._cache.clear()
        self.settingsChanged.emit()
        self._invalidate()
        if self._enabled:
            self._analyze()
        else:
            self.stateChanged.emit()

    @Slot()
    def reset(self):
        self._restored = False
        self._enabled = False
        self._records.clear()
        self.recordsChanged.emit()
        self._cache.clear()
        self._invalidate()
        self._settings = WaterQaSettings()
        self.settingsChanged.emit()
        self.stateChanged.emit()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.reset()
        self._pool.clear()
        self._pool.waitForDone()
        self._tasks.clear()
        self._frame = self._pixels = self._key = None
