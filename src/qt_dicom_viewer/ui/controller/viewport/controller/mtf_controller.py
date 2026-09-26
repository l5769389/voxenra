"""独立于普通测量的单切片 MTF ROI、结果缓存及后台任务。"""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.ui.controller.settings_controller import resolve_settings
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from qt_dicom_viewer import __version__
import math

import numpy as np

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Qt, Signal, Slot

from qt_dicom_viewer.core.measurement_format import format_measurement
from qt_dicom_viewer.core.bead_mtf import (
    compute_mtf_with_context, extract_rect_pixels, gaussian_equivalent_from_mtf10,
)
from qt_dicom_viewer.core.ramp_fwhm import compute_ramp_fwhm, ramp_slice_thickness
from qt_dicom_viewer.model.mtf import BeadMtfResult, RampFwhmResult
from qt_dicom_viewer.model import ImagePoint
from qt_dicom_viewer.model.measure import MeasureContext, MeasurementKind
from .measure.measure_controller import MeasurementController


@dataclass(frozen=True)
class MtfRequest:
    frame_key: tuple
    roi_id: str
    revision: int
    measurement_method: str
    analysis_method: str
    ramp_direction: str = "x"


@dataclass
class _Analysis:
    request: MtfRequest
    result: BeadMtfResult | RampFwhmResult | None = None
    error: str = ""
    preferences: dict = field(default_factory=dict)
    timestamp: str = ""
    fingerprint: str = ""
    source: dict = field(default_factory=dict)
    presented: BeadMtfResult | RampFwhmResult | None = None


class _TaskSignals(QObject):
    completed = Signal(object, object, object)


class _MtfTask(QRunnable):
    def __init__(self, request, pixels, spacing, context=None):
        super().__init__()
        self.request, self.pixels, self.spacing = request, pixels, spacing
        self.context = context
        self.signals = _TaskSignals()

    def run(self):
        try:
            if self.request.measurement_method == "ramp":
                result = compute_ramp_fwhm(self.pixels, *self.spacing,
                    direction=self.request.ramp_direction, analysis_method=self.request.analysis_method)
            else:
                result = compute_mtf_with_context(
                    self.pixels, *self.spacing,
                    context=self.context,
                    measurement_method=self.request.measurement_method,
                    analysis_method=self.request.analysis_method,
                )
        except Exception as exc:
            self.signals.completed.emit(self.request, None, error_message(exc) or _msg('text.0579'))
        else:
            self.signals.completed.emit(self.request, result, "")


class MtfController(QObject):
    TARGET_METHODS = ("bead", "wire")

    _i18n_analysisMethods = Signal()
    _i18n_currentResult = Signal()
    _i18n_error = Signal()
    _i18n_measurementMethods = Signal()
    _i18n_roiMetricLabel = Signal()
    _i18n_statusText = Signal()

    stateChanged = Signal()
    recordsChanged = Signal()
    _i18n_provenance = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings_controller = resolve_settings(parent)
        self._roi = MeasurementController(
            self,
            max_per_frame=1,
            geometry_only=True,
            adaptive_roi_hit_tolerance=True,
            physical_square_roi=self.TARGET_METHODS[0] != "ramp",
        )
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._analyses: dict[str, _Analysis] = {}
        self._records = {}
        self._last_roi_snapshot = {}
        self._restoring_records = False
        self._restored = False
        self._source_error = ""
        self._tasks: dict[MtfRequest, _MtfTask] = {}
        self._revision = 0
        self._measurement_method = self.TARGET_METHODS[0]
        self._analysis_method = "direct_fft" if self._measurement_method == "ramp" else "tukey_fft"
        self._ramp_direction = "x"
        # 点源 MTF 的 X/Y 方向显示选择：默认只看 X，至少保留一个方向。
        self._show_x = True
        self._show_y = False
        self._closed = False
        self._frame = None
        self._pixels = None
        self._roi.measurementCommitted.connect(self._on_committed)
        self._roi.measurementsChanged.connect(self._on_geometry_changed)
        self._roi.activeTransactionChanged.connect(self.stateChanged.emit)
        self._settings_controller.sectionChanged.connect(self._preferences_changed)

    def _pixel_fingerprint(self):
        if self._pixels is None:
            return ""
        return hashlib.blake2b(np.ascontiguousarray(self._pixels).view(np.uint8), digest_size=16).hexdigest()

    @_TextProperty(str, notify=_i18n_provenance, notify_name="_i18n_provenance", source_notify="stateChanged")
    def provenance(self):
        analysis = self._current_analysis()
        if analysis is None or not analysis.timestamp:
            return ""
        record = self._records.get(analysis.request.roi_id, {})
        return _msg("analysis.provenance", value1=record.get("app", __version__),
                    value2=record.get("algorithm", "1"), value3=analysis.timestamp)

    def persistent_state(self):
        return dict(version=1, roi=self._roi.persistent_state(), records=dict(self._records),
                    method=self._measurement_method, analysis=self._analysis_method,
                    direction=self._ramp_direction, showX=self._show_x, showY=self._show_y)

    def restore_state(self, state):
        if not state or state.get("version") != 1:
            return
        self._revision += 1
        self._analyses.clear()
        self._restoring_records = True
        self._roi.restore_state(state.get("roi", {}))
        self._last_roi_snapshot = self._roi.persistent_state()
        self._restoring_records = False
        self._records = dict(state.get("records", {}))
        self._measurement_method = state.get("method", self._measurement_method)
        self._analysis_method = state.get("analysis", self._analysis_method)
        self._ramp_direction = state.get("direction", "x")
        self._show_x, self._show_y = state.get("showX", True), state.get("showY", False)
        self._restored = bool(self._records or self._roi.committed_measurements)
        for mid, record in self._records.items():
            current = next((m for m in self._roi.committed_measurements if m.measurement_id == mid), None)
            if current != record["roi"]:
                continue
            req = MtfRequest(record["frame"], mid, self._revision, record["method"], record["analysis"], record["direction"])
            self._analyses[mid] = _Analysis(req, record["result"], preferences=dict(record["preferences"]),
                timestamp=record["timestamp"], fingerprint=record.get("fingerprint", ""),
                source=record.get("source", {}), presented=record.get("presented"))
        if self._frame is not None:
            self.set_frame(self._roi.frame_key[0], self._frame, self._pixels)
        self.stateChanged.emit()

    @Slot()
    def recalculate(self):
        self._source_error = ""
        self._roi.source_valid = True
        visible = self._roi.visible_measurements
        if self._frame is not None and visible and not self._roi.has_active_transaction:
            self._schedule(visible[-1])
            self.recordsChanged.emit()
            self.stateChanged.emit()

    def _preferences_changed(self, section):
        if section in ("measurement", "services"):
            self.stateChanged.emit()

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    @Property(QObject, constant=True)
    def roiController(self):
        return self._roi

    @_TextProperty('QVariantList', notify=_i18n_measurementMethods, notify_name='_i18n_measurementMethods')
    def measurementMethods(self):
        labels = {"bead": _msg('text.0248'), "wire": _msg('text.0580'), "ramp": _msg('ramp.target')}
        return [{"value": method, "label": labels[method]} for method in self.TARGET_METHODS]

    @_TextProperty('QVariantList', notify=_i18n_analysisMethods, notify_name='_i18n_analysisMethods', source_notify='stateChanged')
    def analysisMethods(self):
        methods = [] if self._measurement_method == "ramp" else [
            {"value": "tukey_fft", "label": _msg('mtf.weightedMethod')}]
        return methods + [
            {"value": "direct_fft", "label": _msg('ramp.halfHeight') if self._measurement_method == "ramp" else _msg('text.0581')},
            {"value": "gaussian", "label": _msg('text.0582')},
        ]

    @Property(str, notify=stateChanged)
    def measurementMethod(self):
        return self._measurement_method

    @Property(str, notify=stateChanged)
    def analysisMethod(self):
        return self._analysis_method

    @Property(str, notify=stateChanged)
    def rampDirection(self):
        return self._ramp_direction

    @Property(bool, notify=stateChanged)
    def showX(self):
        return self._show_x

    @Property(bool, notify=stateChanged)
    def showY(self):
        return self._show_y

    @Slot(bool)
    def setShowX(self, visible):
        visible = bool(visible)
        # 至少保留一个方向：拒绝关闭唯一可见的方向。
        if visible == self._show_x or (not visible and not self._show_y):
            return
        self._show_x = visible
        self.recordsChanged.emit()
        self.stateChanged.emit()

    @Slot(bool)
    def setShowY(self, visible):
        visible = bool(visible)
        if visible == self._show_y or (not visible and not self._show_x):
            return
        self._show_y = visible
        self.recordsChanged.emit()
        self.stateChanged.emit()

    @Property(int, notify=stateChanged)
    def rampAngle(self):
        analysis = self._current_analysis()
        return (analysis.preferences if analysis and analysis.preferences else self._settings_controller.section("services"))["rampThicknessAngle"]

    @Slot(str)
    def setRampDirection(self, direction):
        if direction not in ("x", "y") or direction == self._ramp_direction:
            return
        self._ramp_direction = direction
        self.recordsChanged.emit()
        if self._measurement_method == "ramp":
            visible = self._roi.visible_measurements
            if visible and self._frame is not None:
                self._schedule(visible[-1])
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)
    def actualAnalysisMethod(self):
        result = self._presented_result()
        return result.analysis_method if result is not None else ""

    def _presented_result(self):
        if self.status != "ready":
            return None
        if self._current_analysis().presented is not None:
            return self._current_analysis().presented
        result = self._current_analysis().result
        if (isinstance(result, BeadMtfResult)
                and (self._current_analysis().preferences or self._settings_controller.section("services"))["mtfGaussianEquivalent"]):
            return gaussian_equivalent_from_mtf10(result)
        return result

    @Property(str, notify=stateChanged)
    def frequencyUnit(self):
        return self._settings_controller.section("services")["mtfFrequencyUnit"]

    def _display_frequency(self, value):
        # Cached analysis stays in lp/mm; convert only the presentation copy.
        return None if value is None else value * (10.0 if self.frequencyUnit == "lp/cm" else 1.0)

    @Property('QVariantMap', notify=stateChanged)
    def roiGeometry(self):
        """Source-image coordinates, with physical dimensions in mm."""
        if self._closed or self._frame is None or self._pixels is None or np.ndim(self._pixels) != 2:
            return {}
        spacing = self._frame.instance_meta.pixel_spacing
        if not spacing or not all(v is not None and math.isfinite(v) and v > 0 for v in spacing):
            return {}
        rows, columns = self._pixels.shape
        side = min(10., columns * spacing[1] / 2, rows * spacing[0] / 2)
        geometry = dict(centerX=(columns-1)/2, centerY=(rows-1)/2,
                        width=side, height=side, columns=columns, rows=rows)
        visible = self._roi.visible_measurements
        if visible:
            a, b = visible[-1].points
            geometry.update(centerX=(a.column+b.column)/2, centerY=(a.row+b.row)/2,
                            width=abs(b.column-a.column)*spacing[1],
                            height=abs(b.row-a.row)*spacing[0])
        return geometry

    @Slot(float, float, float, float, result=bool)
    def applyRoi(self, center_x, center_y, width_mm, height_mm):
        """Apply atomically; invalid input leaves the existing ROI/result intact."""
        if not self.roiGeometry or self._roi.has_active_transaction:
            return False
        if (not all(math.isfinite(v) for v in (center_x, center_y, width_mm, height_mm))
                or width_mm <= 0 or height_mm <= 0):
            return False
        if self._measurement_method != 'ramp':
            height_mm = width_mm
        row_spacing, column_spacing = self._frame.instance_meta.pixel_spacing
        dx, dy = width_mm / column_spacing / 2, height_mm / row_spacing / 2
        points = [ImagePoint(center_x-dx, center_y-dy), ImagePoint(center_x+dx, center_y+dy)]
        try:
            extract_rect_pixels(self._pixels, points,
                                minimum_side=1 if self._measurement_method == 'ramp' else 8)
        except (ValueError, TypeError):
            return False
        context = MeasureContext(
            measurement_kind=MeasurementKind.RECT, series_uid=self._roi.frame_key[0],
            sop_instance_uid=self._frame.instance_meta.sop_instance_uid or '',
            slice_index=self._frame.slice_index, geometry=self._frame.geometry,
            endpoint_tolerance=0, line_tolerance=0)
        return self._roi.commit_service_rectangle(points, context)

    @Property(str, notify=stateChanged)
    def frameToken(self):
        return repr(self._roi.frame_key) if self._frame is not None else ''

    @Property('QVariantMap', notify=stateChanged)
    def stateSnapshot(self):
        """Ready means numerical completion, not GPU presentation."""
        return dict(status=self.status,
                    frameToken=self.frameToken,
                    sliceNumber=self._frame.slice_index + 1 if self._frame else None,
                    measurementMethod=self.measurementMethod,
                    requestedMethod=self.analysisMethod, actualMethod=self.actualAnalysisMethod,
                    frequencyUnit=self.frequencyUnit, roi=self.roiGeometry,
                    result=self.currentResult, error=self.error, warnings=self.warnings)

    @Slot(str)
    def setMeasurementMethod(self, method):
        if method == self._measurement_method:
            return
        if method not in {item["value"] for item in self.measurementMethods}:
            return
        # 不同测试体对 ROI 的语义不同，不能静默复用旧框。
        self._measurement_method = method
        self._analyses.clear()
        self._roi.clear_all()
        self._roi.set_physical_square_roi(method != "ramp")
        self.stateChanged.emit()

    @Slot(str)
    def setAnalysisMethod(self, method):
        if method == self._analysis_method:
            return
        if method not in {item["value"] for item in self.analysisMethods}:
            return
        self._analysis_method = method
        self.recordsChanged.emit()
        # Recalculate only this ROI; other slices keep their recorded method/result.
        visible = self._roi.visible_measurements
        if visible and self._frame is not None:
            self._schedule(visible[-1])
        self.stateChanged.emit()

    def set_frame(self, series_uid, frame, pixels):
        if self._closed:
            return
        self._frame, self._pixels = frame, pixels
        self._source_error = ""
        self._roi.source_valid = True
        self._roi.set_frame(series_uid, frame)
        visible = self._roi.visible_measurements
        if visible:
            saved = self._analyses.get(visible[-1].measurement_id)
            if saved:
                self._measurement_method = saved.request.measurement_method
                self._analysis_method = saved.request.analysis_method
                self._ramp_direction = saved.request.ramp_direction
            if saved and saved.fingerprint and saved.fingerprint != self._pixel_fingerprint():
                self._source_error = _msg("analysis.sourceMismatch")
                self._roi.source_valid = False
                self._roi.measurementsChanged.emit()
        if self._restored and not visible and any(
                record["frame"][:3] == self._roi.frame_key[:3]
                and record["frame"] != self._roi.frame_key for record in self._records.values()):
            self._source_error = _msg("analysis.sourceMismatch")
            self._roi.source_valid = False
        if visible and self._current_analysis() is None and not self._restored:
            # 分析方式切换后，其他切片的 ROI 在再次显示时按当前方式惰性重算。
            self._schedule(visible[-1])
        self.stateChanged.emit()

    def set_current_slice(self, index):
        self._frame, self._pixels = None, None
        self._source_error = ""
        self._roi.set_current_slice(index)
        self.stateChanged.emit()

    def _current_analysis(self):
        visible = self._roi.visible_measurements
        if self._frame is None or not visible:
            return None
        analysis = self._analyses.get(visible[-1].measurement_id)
        if (analysis and analysis.request.frame_key == self._roi.frame_key
                and analysis.request.measurement_method == self._measurement_method
                and analysis.request.analysis_method == self._analysis_method
                and (self._measurement_method != "ramp" or analysis.request.ramp_direction == self._ramp_direction)):
            return analysis
        return None

    @Property(str, notify=stateChanged)
    def status(self):
        if self._source_error:
            return "error"
        if self._roi.activeTransaction:
            return "editing"
        analysis = self._current_analysis()
        if analysis is None:
            return "empty"
        if analysis.error:
            return "error"
        return "ready" if analysis.result else "calculating"

    @_TextProperty(str, notify=_i18n_statusText, notify_name='_i18n_statusText', source_notify='stateChanged')
    def statusText(self):
        if self._measurement_method == "ramp" and self.status == "empty":
            return _msg('ramp.drawHint')
        source = _msg('text.0583') if self._measurement_method == "bead" else _msg('text.0584')
        return {"editing": _msg('text.0585'), "empty": _msg('text.0586', value1=source),
                "error": _msg('text.0587'), "ready": "",
                "calculating": _msg('text.0588')}[self.status]

    @_TextProperty(str, notify=_i18n_roiMetricLabel, notify_name='_i18n_roiMetricLabel', source_notify='stateChanged')
    def roiMetricLabel(self):
        if self._frame is None:
            return ""
        places = self._settings_controller.section("measurement")["decimalPlaces"]

        def metric(value):
            return _msg('text.0589') if value is None else format_measurement(value, places)

        # Geometry is available while drawing and when analysis fails. Never
        # reuse cached geometry/results while a control point is being moved.
        draft = self._roi.activeTransaction
        if draft:
            points = [(p['column'], p['row']) for p in draft.get('points', [])]
        else:
            visible = self._roi.visible_measurements
            points = [(p.column, p.row) for p in visible[-1].points] if visible else []
        if len(points) != 2:
            return ""
        width, height = (abs(points[1][i]-points[0][i]) for i in (0, 1))
        spacing = self._frame.instance_meta.pixel_spacing
        physical = (spacing is not None and len(spacing) == 2
                    and all(v is not None and math.isfinite(v) and v > 0 for v in spacing))
        if physical:
            width, height = width*spacing[1], height*spacing[0]
        unit = 'mm' if physical else 'px'
        basic = f"ROI  {metric(width)} × {metric(height)} {unit} · {metric(width*height)} {unit}²"
        if self.status != 'ready':
            return basic
        result = self._presented_result()
        if isinstance(result, RampFwhmResult):
            thickness = ramp_slice_thickness(result.fwhm, self.rampAngle)
            return (f"{basic}\n"
                    f"FWHM  {metric(result.fwhm)} mm\n"
                    + _msg('ramp.thicknessLabel', angle=self.rampAngle, value=metric(thickness)))
        axes = []
        if self._show_x:
            axes.append(("X", result.x))
        if self._show_y:
            axes.append(("Y", result.y))
        def frequency_metric(axis, name):
            return "—" if name in axis.unreliable_metrics else metric(self._display_frequency(getattr(axis, name)))

        line50 = " · ".join(f"{name} {frequency_metric(axis, 'mtf50')}" for name, axis in axes)
        line10 = " · ".join(f"{name} {frequency_metric(axis, 'mtf10')}" for name, axis in axes)
        return (
            f"{basic}\n"
            f"MTF50  {line50} {self.frequencyUnit}\n"
            f"MTF10  {line10} {self.frequencyUnit}"
        )

    @_TextProperty('QVariantMap', notify=_i18n_currentResult, notify_name='_i18n_currentResult', source_notify='stateChanged')
    def currentResult(self):
        analysis = self._current_analysis()
        if self.status != "ready":
            return {}
        if isinstance(analysis.result, RampFwhmResult):
            ramp = asdict(analysis.result)
            for field in ("profile", "fitted"):
                ramp[field] = list(ramp[field])
            ramp["thickness"] = ramp_slice_thickness(analysis.result.fwhm, self.rampAngle)
            return {"ramp": ramp}
        # QML 图表只消费两个方向；状态、警告和方法已有独立属性，不重复复制。
        result = self._presented_result()
        payload = {direction: asdict(getattr(result, direction))
                   for direction in ("x", "y")}
        scale = 10.0 if self.frequencyUnit == "lp/cm" else 1.0
        # 显式列表才能稳定地转换为 QML 可遍历的 QVariantList，而不是 Python 元组对象。
        for direction in ("x", "y"):
            for field in ("lsf", "frequency", "mtf", "unreliable_metrics"):
                payload[direction][field] = list(payload[direction][field])
            axis = payload[direction]
            axis["frequency"] = [value * scale for value in axis["frequency"]]
            for field in ("mtf50", "mtf10"):
                axis[field] = self._display_frequency(axis[field])
        return payload

    @_TextProperty(str, notify=_i18n_error, notify_name='_i18n_error', source_notify='stateChanged')
    def error(self):
        if self._source_error:
            return self._source_error
        analysis = self._current_analysis()
        return analysis.error if self.status == "error" else ""

    @Property("QStringList", notify=stateChanged)
    def warnings(self):
        result = self._presented_result()
        return list(result.warnings) if result is not None else []

    @Slot()
    def _on_geometry_changed(self):
        retained = {m.measurement_id for m in self._roi.committed_measurements}
        self._analyses = {key: value for key, value in self._analyses.items() if key in retained}
        self._records = {k:v for k,v in self._records.items() if k in retained}
        current = self._roi.persistent_state()
        if current != self._last_roi_snapshot:
            self._last_roi_snapshot = current
            if not self._restoring_records:
                self.recordsChanged.emit()
        self.stateChanged.emit()

    @Slot(object)
    def _on_committed(self, measurement):
        if self._closed or self._frame is None:
            return
        self._schedule(measurement)
        self.stateChanged.emit()

    def _schedule(self, measurement):
        """为已提交 ROI 创建带方法版本的后台请求。"""
        self._source_error = ""
        self._roi.source_valid = True
        self._revision += 1
        request = MtfRequest(
            self._roi.frame_key,
            measurement.measurement_id,
            self._revision,
            self._measurement_method,
            self._analysis_method,
            self._ramp_direction,
        )
        analysis = _Analysis(request, preferences=dict(self._settings_controller.section("services")),
                             fingerprint=self._pixel_fingerprint(), source=dict(
                                 sop=self._frame.instance_meta.sop_instance_uid,
                                 frameIndex=self._frame.instance_meta.frame_index,
                                 sliceIndex=self._frame.slice_index,
                                 pixelSpacing=self._frame.instance_meta.pixel_spacing))
        self._analyses[measurement.measurement_id] = analysis
        try:
            snapshot = extract_rect_pixels(self._pixels, measurement.points,
                minimum_side=1 if self._measurement_method == "ramp" else 8)
            # 元数据中的原始 PixelSpacing 不存在时，不能借用显示几何的 1 mm 回退值。
            spacing = self._frame.instance_meta.pixel_spacing
            if spacing is None:
                raise ValueError(_msg('text.0590'))
            context = None
            if self._measurement_method != 'ramp' and self._analysis_method == 'tukey_fft':
                origin = (math.ceil(min(p.row for p in measurement.points)),
                          math.ceil(min(p.column for p in measurement.points)))
                image = np.array(self._pixels, dtype=np.float64, copy=True)
                image.setflags(write=False)
                context = (image, origin)
            self._submit(request, snapshot, spacing, context)
        except (ValueError, TypeError) as exc:
            analysis.error = error_message(exc)

    def _submit(self, request, snapshot, spacing, context=None):
        """只在提交后调用，任务持有像素副本而不访问视口或 QML 对象。"""
        task = _MtfTask(request, snapshot, spacing, context)
        self._tasks[request] = task
        task.signals.completed.connect(self._receive_result, Qt.ConnectionType.QueuedConnection)
        self._pool.start(task)

    @Slot(object, object, object)
    def _receive_result(self, request, result, error):
        self._tasks.pop(request, None)
        analysis = self._analyses.get(request.roi_id)
        if self._closed or analysis is None or analysis.request != request:
            return
        # 非当前切片允许保存仍然有效的结果，但属性始终只返回当前切片的缓存。
        analysis.result, analysis.error = result, error
        if result is not None and not error:
            analysis.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            roi = next((m for m in self._roi.committed_measurements if m.measurement_id == request.roi_id), None)
            analysis.presented = (gaussian_equivalent_from_mtf10(result)
                if isinstance(result, BeadMtfResult) and analysis.preferences.get("mtfGaussianEquivalent") else result)
            self._records[request.roi_id] = dict(frame=request.frame_key, roi=roi, source=analysis.source,
                method=request.measurement_method, analysis=request.analysis_method,
                direction=request.ramp_direction, result=result,
                presented=analysis.presented, preferences=analysis.preferences,
                timestamp=analysis.timestamp, fingerprint=analysis.fingerprint, algorithm="1", app=__version__)
            self.recordsChanged.emit()
        self.stateChanged.emit()

    @Slot()
    def reset(self):
        self._restored = False
        self._source_error = ""
        self._roi.source_valid = True
        self._analyses.clear()
        self._records.clear()
        self._roi.clear_all()
        self.recordsChanged.emit()
        self.stateChanged.emit()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.reset()
        self._pool.clear()
        # 当前纯数值任务结束后再销毁信号对象，避免关闭标签页时跨线程访问已销毁对象。
        self._pool.waitForDone()
        self._tasks.clear()
        self._pixels = None
