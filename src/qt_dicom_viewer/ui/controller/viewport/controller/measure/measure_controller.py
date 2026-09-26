"""统一管理测量创建、编辑、选中及切面隔离，几何计算交给无状态操作。"""
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty

import math
from dataclasses import asdict, replace

from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.core.geometry_2d import point_distance
from qt_dicom_viewer.core.measurement_format import format_measurement
from qt_dicom_viewer.ui.controller.settings_controller import resolve_settings
from qt_dicom_viewer.core.measurement_hit_test import (
    hit_test_control_points,
    hit_test_interior,
    hit_test_label,
    hit_test_outline,
    nearest_hit,
)
from qt_dicom_viewer.model import DragUpdateEvent, ImagePoint, Offset, Point, PointerPosition
from qt_dicom_viewer.model.dicom_types import FrameDisplayMeta
from qt_dicom_viewer.model.measure import (
    AngleMeasurement, AngleMeasurementDraft, AnglePointIndex,
    CreateMeasurementTransaction, EditMeasurementTransaction, EditTargetKind,
    LengthMeasurement, LengthMeasurementDraft, MeasureContext, Measurement,
    MeasurementDraft, MeasurementEditTarget, MeasurementHit, MeasurementKind,
    MeasurementLabelRegion, MeasurementTransaction, RoiMeasurement, RoiMeasurementDraft,
)
from qt_dicom_viewer.ui.controller.viewport.operation.angle_measure_operation import AngleMeasureOperation
from qt_dicom_viewer.ui.controller.viewport.operation.length_measure_operation import LengthMeasureOperation
from qt_dicom_viewer.ui.controller.viewport.operation.roi_measure_operation import RoiMeasureOperation


class MeasurementController(QObject):
    _i18n_instruction = Signal()
    _i18n_measurementItems = Signal()


    measurementsChanged = Signal()
    activeTransactionChanged = Signal()
    selectionChanged = Signal()
    hoverChanged = Signal()
    measurementCommitted = Signal(object)

    def __init__(self, parent: QObject | None = None, *,
                 max_per_frame: int | None = None, geometry_only: bool = False,
                 adaptive_roi_hit_tolerance: bool = False,
                 physical_square_roi: bool = False):
        super().__init__(parent)
        self._settings_controller = resolve_settings(parent)
        self._decimal_places = self._settings_controller.section("measurement")["decimalPlaces"]
        self._settings_controller.sectionChanged.connect(self._preferences_changed)
        self._max_per_frame = max_per_frame
        self.secondary_pixels = None
        self._current_frame = None
        self._geometry_only = geometry_only
        self._adaptive_roi_hit_tolerance = adaptive_roi_hit_tolerance
        self._measurements: dict[str, Measurement] = {}
        self._active_transaction: MeasurementTransaction | None = None
        self._selected_measurement_id: str | None = None
        # Selection styling is independent of the committed geometry / drag transaction.
        self._selected_measurement_state = "none"
        self._selection_before_edit = "completed"
        self._hover_hit: MeasurementHit | None = None
        self._length_operation = LengthMeasureOperation()
        self._angle_operation = AngleMeasureOperation()
        self._roi_operation = RoiMeasureOperation(
            physical_square=physical_square_roi
        )
        self._drag_reference: MeasurementDraft | None = None
        self._drag_start: PointerPosition | None = None
        self._frame_key: tuple | None = None
        self._measurement_frames: dict[str, tuple | None] = {}
        self._presentation = {}
        self._sources = {}
        self.current_source = {}
        self.source_valid = True
        self._visible_slice: int | None = None
        self._label_positions: dict[str, ImagePoint] = {}
        self._label_origins: dict[str, ImagePoint] = {}
        self._label_drag = None
        self._path_invalid = False
        self._path_preview = None
        self._linked_label_reference = None
        self._label_regions: dict[str, MeasurementLabelRegion] = {}
        # 标签布局来自 QML；模型增删、编辑或切面变化后，等待下次输入前重新提供。
        self.measurementsChanged.connect(self._label_regions.clear)
        self.measurementsChanged.connect(self.clearHover)
        self.activeTransactionChanged.connect(self.clearHover)
        # 选择变化会改变光标语义，但不改变“鼠标命中了哪个部位”这一事实。
        self.selectionChanged.connect(self.hoverChanged.emit)

    def presentation(self, measurement_id):
        return dict(name="", hidden=False, locked=False) | self._presentation.get(measurement_id, {})

    def measurement_name(self, measurement):
        info = self.presentation(measurement.measurement_id)
        kind = "angle" if isinstance(measurement, AngleMeasurement) else str(measurement.kind)
        label = {"length": _msg("text.0321"), "angle": _msg("text.0322"),
                 "curve": _msg("measurement.curve"), "arrow": _msg("text.0377")}.get(kind, "ROI")
        ordinal = info.get("ordinal", list(self._measurements).index(measurement.measurement_id) + 1)
        return info["name"] or label + f" {ordinal}"

    def source(self, measurement_id):
        return dict(self._sources.get(measurement_id, {}))

    def frame_for(self, measurement_id):
        return self._measurement_frames.get(measurement_id)

    def update_presentation(self, measurement_id, **changes):
        if measurement_id not in self._measurements:
            return
        self.cancel_transaction()
        value = self.presentation(measurement_id)
        value.update(changes)
        self._presentation[measurement_id] = value
        if value["hidden"]:
            self.clear_selection()
        self.measurementsChanged.emit()

    def delete_measurement(self, measurement_id):
        if measurement_id not in self._measurements:
            return
        self.cancel_transaction()
        self._measurements.pop(measurement_id, None)
        self._measurement_frames.pop(measurement_id, None)
        self._presentation.pop(measurement_id, None)
        self._sources.pop(measurement_id, None)
        self._label_positions.pop(measurement_id, None)
        self.clear_selection()
        self.measurementsChanged.emit()

    def persistent_state(self):
        keys = self._measurements
        return dict(measurements=dict(keys), frames=dict(self._measurement_frames),
                    labelPositions={k:v for k,v in self._label_positions.items() if k in keys},
                    presentation={k:dict(v) for k,v in self._presentation.items() if k in keys},
                    sources={k:dict(v) for k,v in self._sources.items() if k in keys})

    def restore_state(self, record):
        self.cancel_transaction()
        self.clear_selection()
        self._measurements = dict(record.get("measurements", {}))
        self._measurement_frames = dict(record.get("frames", {}))
        self._label_positions = dict(record.get("labelPositions", {}))
        self._presentation = dict(record.get("presentation", {}))
        self._sources = dict(record.get("sources", {}))
        self.measurementsChanged.emit()

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    def _preferences_changed(self, section):
        if section != "measurement":
            return
        places = self._settings_controller.section("measurement")["decimalPlaces"]
        if places != self._decimal_places:
            self._decimal_places = places
            if not self._geometry_only:
                self.measurementsChanged.emit()
                self.activeTransactionChanged.emit()

    def set_physical_square_roi(self, enabled: bool) -> None:
        """Change the constraint for future edits after cancelling the draft."""
        self.cancel_transaction()
        self._roi_operation = RoiMeasureOperation(physical_square=enabled)

    def set_frame(self, series_uid: str, frame: FrameDisplayMeta, *, source_context: tuple = ()) -> None:
        """MPR 的索引不足以识别切面；同时比较采样原点、方向、尺寸和间距。"""
        self._current_frame = frame
        geometry = frame.geometry
        pose = (geometry.pixel_spacing.row, geometry.pixel_spacing.column,
                *(geometry.image_position_patient or ()),
                *(geometry.image_orientation_patient or ()))
        if self._geometry_only:
            # MTF 使用原始间距而非显示回退值，两者变化时不能复用旧分析。
            pose += tuple(frame.instance_meta.pixel_spacing or (None, None))
        key = (series_uid, frame.instance_meta.sop_instance_uid, frame.slice_index,
               geometry.rows, geometry.columns,
               tuple(round(v, 7) if isinstance(v, (int, float)) and math.isfinite(v) else str(v)
                     for v in pose))
        # Projection measurements must retain their sampling origin
        # after display settings change, including history/workspace round trips.
        if source_context:
            key += (source_context,)
        if key == self._frame_key and self._visible_slice == frame.slice_index:
            return
        self.cancel_transaction()
        self.clear_selection()
        self._frame_key = key
        self._visible_slice = frame.slice_index
        self.measurementsChanged.emit()

    def set_current_slice(self, index: int) -> None:
        self.cancel_transaction()
        self.clear_selection()
        self._visible_slice = index
        self.measurementsChanged.emit()

    def _visible(self, measurement: Measurement) -> bool:
        return (self.source_valid and not self.presentation(measurement.measurement_id)["hidden"]
                and (self._visible_slice is None or measurement.slice_index == self._visible_slice)
                and self._measurement_frames.get(measurement.measurement_id) == self._frame_key)

    @property
    def frame_key(self) -> tuple | None:
        return self._frame_key

    @property
    def committed_measurements(self) -> tuple[Measurement, ...]:
        return tuple(self._measurements.values())

    @property
    def visible_measurements(self) -> tuple[Measurement, ...]:
        return tuple(m for m in self._measurements.values() if self._visible(m))

    @_TextProperty('QVariantList', notify=_i18n_measurementItems, notify_name='_i18n_measurementItems', source_notify='measurementsChanged')
    def measurementItems(self) -> list[dict]:
        editing_id = (self._active_transaction.draft.measurement_id
                      if isinstance(self._active_transaction, EditMeasurementTransaction) else None)
        return [self._to_qml_item(m) for key, m in self._measurements.items()
                if key != editing_id and self._visible(m)]

    @Property('QVariantMap', notify=activeTransactionChanged)
    def activeTransaction(self) -> dict:
        transaction = self._active_transaction
        if transaction is None:
            return {}
        item = self._to_qml_item(transaction.draft)
        item["editTarget"] = {"kind": transaction.target.kind.value, "index": transaction.target.index}
        item["creating"] = isinstance(transaction, CreateMeasurementTransaction)
        if self._creating_path() and self._path_preview is not None:
            preview = self._path_preview
            item["renderPoints"] = item["points"] + [{"column": preview.column, "row": preview.row}]
            if transaction.draft.kind == MeasurementKind.FREEHAND and transaction.draft.smooth:
                from qt_dicom_viewer.core.freehand_roi import roi_outline
                controls = self._path_preview_points(preview)
                boundary = roi_outline(controls, True) if len(controls) >= 3 else controls
                item["renderPoints"] = [{"column": p.column, "row": p.row} for p in boundary]
            if transaction.draft.kind == MeasurementKind.CURVE:
                from qt_dicom_viewer.core.curve_geometry import sample_curve
                item["renderPoints"] = [{"column": p.column, "row": p.row}
                    for p in sample_curve(self._path_preview_points(preview))]
        if self._creating_angle() and transaction.target.index == AnglePointIndex.VERTEX:
            item["label"] = _msg('text.0606')
        return item

    @_TextProperty(str, notify=_i18n_instruction, notify_name='_i18n_instruction', source_notify='activeTransactionChanged')
    def instruction(self) -> str:
        if self._creating_path():
            return _msg("measurement.pathInvalid") if self._path_invalid else _msg("measurement.pathHint")
        if self._creating_angle():
            return (_msg('text.0607') if self._active_transaction.target.index == AnglePointIndex.VERTEX
                    else _msg('text.0608'))
        return ""

    @Property(str, notify=selectionChanged)
    def selectedMeasurementId(self) -> str:
        return self._selected_measurement_id or ""

    @Property(str, notify=selectionChanged)
    def selectedMeasurementState(self) -> str:
        """none / completed after release / draft after an explicit selection click."""
        return self._selected_measurement_state

    @Property('QVariantMap', notify=hoverChanged)
    def hoverHit(self) -> dict:
        hit = self._hover_hit
        if hit is None:
            return {}
        return {"measurementId": hit.measurement_id,
                "kind": hit.target.kind.value, "index": hit.target.index}

    @Property(str, notify=hoverChanged)
    def hoverCursorKind(self) -> str:
        """仅选中图形的可整体移动部位显示移动图标，控制点保持调整形状的语义。"""
        hit = self._hover_hit
        if (hit is not None and not self.presentation(hit.measurement_id)["locked"] and not self.has_active_transaction
                and hit.measurement_id == self._selected_measurement_id
                and hit.target.kind in (EditTargetKind.OUTLINE, EditTargetKind.INTERIOR, EditTargetKind.LABEL)):
            return "pan"
        return ""

    def update_hover(self, point: ImagePoint | None, *, slice_index: int,
                     endpoint_tolerance: float, line_tolerance: float,
                     viewport_point: Point | None = None) -> None:
        """悬停只判断命中，不改变选择、不修改图形，也不计算像素统计。"""
        hit = None
        if point is not None and not self.has_active_transaction:
            hit = self.hit_test(point, slice_index=slice_index,
                                endpoint_tolerance=endpoint_tolerance, line_tolerance=line_tolerance,
                                viewport_point=viewport_point)
        # 光标只关心部位和所属图形；沿同一轮廓移动时无需因距离变化反复通知 QML。
        before = (self._hover_hit.measurement_id, self._hover_hit.target) if self._hover_hit else None
        after = (hit.measurement_id, hit.target) if hit else None
        self._hover_hit = hit
        if before != after:
            self.hoverChanged.emit()

    @Slot()
    def clearHover(self) -> None:
        if self._hover_hit is not None:
            self._hover_hit = None
            self.hoverChanged.emit()

    @property
    def has_active_transaction(self) -> bool:
        return self._active_transaction is not None or self._label_drag is not None

    def _to_qml_item(self, measurement: Measurement | MeasurementDraft) -> dict:
        item = {"locked": self.presentation(measurement.measurement_id)["locked"], "measurementId": measurement.measurement_id,
                "points": [{"column": p.column, "row": p.row} for p in measurement.points]}
        if isinstance(measurement, (LengthMeasurement, LengthMeasurementDraft)):
            item.update(type=measurement.kind.value, startColumn=measurement.points[0].column,
                        startRow=measurement.points[0].row, endColumn=measurement.points[-1].column,
                        endRow=measurement.points[-1].row, label="" if measurement.kind == MeasurementKind.ARROW else f"{format_measurement(measurement.length_mm, self._decimal_places)} mm")
            if measurement.kind == MeasurementKind.CURVE:
                from qt_dicom_viewer.core.curve_geometry import sample_curve
                item["renderPoints"] = [{"column": p.column, "row": p.row} for p in sample_curve(measurement.points)]
        elif isinstance(measurement, (AngleMeasurement, AngleMeasurementDraft)):
            label = f"{format_measurement(measurement.angle, self._decimal_places)}°"
            item.update(type="angle", label=label)
        else:
            item["smooth"] = measurement.smooth
            if measurement.kind == MeasurementKind.FREEHAND:
                from qt_dicom_viewer.core.freehand_roi import roi_outline
                boundary = roi_outline(measurement.points, measurement.smooth) if len(measurement.points) >= 3 else measurement.points
                item["renderPoints"] = [{"column": p.column, "row": p.row} for p in boundary]
            item.update(type=measurement.kind.value, metrics=asdict(measurement.metrics),
                        label=_msg('measurement.freehand') if measurement.kind == MeasurementKind.FREEHAND else _msg('text.0375') if measurement.kind == MeasurementKind.RECT else _msg('text.0376'))
            if self.secondary_pixels is not None and self._current_frame is not None:
                from qt_dicom_viewer.core.measurement_geometry import roi_metrics
                spacing = self._current_frame.geometry.pixel_spacing
                item["secondaryMetrics"] = asdict(roi_metrics(measurement.points,
                    measurement.kind, self.secondary_pixels, row_spacing=spacing.row,
                    column_spacing=spacing.column, unit="HU", smooth=measurement.smooth))
        anchor = self._label_positions.get(measurement.measurement_id)
        if anchor is not None:
            item["labelPosition"] = {"column": anchor.column, "row": anchor.row}
        return item

    def _operation(self, measurement: Measurement | MeasurementDraft):
        if isinstance(measurement, (LengthMeasurement, LengthMeasurementDraft)):
            return self._length_operation
        if isinstance(measurement, (AngleMeasurement, AngleMeasurementDraft)):
            return self._angle_operation
        return self._roi_operation

    def _creating_path(self):
        return (isinstance(self._active_transaction, CreateMeasurementTransaction)
                and getattr(self._active_transaction.draft, "kind", None)
                in (MeasurementKind.FREEHAND, MeasurementKind.CURVE))

    def _path_preview_points(self, point):
        transaction = self._active_transaction
        controls = transaction.draft.points
        # Hovering near an existing end previews snapping, not a tiny extra span.
        tolerance = transaction.context.endpoint_tolerance
        if (point_distance(controls[-1], point) <= tolerance
                or (transaction.draft.kind == MeasurementKind.FREEHAND
                    and point_distance(controls[0], point) <= tolerance)):
            return controls
        return [*controls, point]

    @staticmethod
    def _valid_path_points(points, kind, smooth=False):
        if kind == MeasurementKind.CURVE:
            from qt_dicom_viewer.core.curve_geometry import sample_curve
            return len(points) >= 2 and bool(sample_curve(points))
        from qt_dicom_viewer.core.freehand_roi import simple_polygon, roi_outline
        # Smooth outlines are already checked and cached by roi_outline.
        return bool(roi_outline(points, True)) if smooth else simple_polygon(points)

    def _append_path_point(self, point):
        draft = self._active_transaction.draft
        self._path_invalid = False
        if (draft.kind == MeasurementKind.FREEHAND and len(draft.points) >= 3
                and point_distance(draft.points[0], point) <= self._active_transaction.context.endpoint_tolerance):
            self.finish_path()
            return
        if point_distance(draft.points[-1], point) > 1e-6 and len(draft.points) < 4096:
            candidate = [*draft.points, point]
            if (len(candidate) >= (3 if draft.kind == MeasurementKind.FREEHAND else 2)
                    and not self._valid_path_points(candidate, draft.kind, getattr(draft, 'smooth', False))):
                self._path_invalid = True
                self.activeTransactionChanged.emit()
                return
            draft.points.append(point)
        if draft.kind == MeasurementKind.CURVE:
            from qt_dicom_viewer.core.curve_geometry import curve_length_mm
            spacing = self._active_transaction.context.geometry.pixel_spacing
            draft.length_mm = curve_length_mm(draft.points, spacing.row, spacing.column)
        self._path_preview = None
        self.activeTransactionChanged.emit()

    def finish_path(self):
        if not self._creating_path():
            return False
        transaction = self._active_transaction
        if len(transaction.draft.points) < 3:
            return True  # Keep the unfinished path available for more clicks.
        if not self._valid_path_points(transaction.draft.points, transaction.draft.kind,
                                       getattr(transaction.draft, 'smooth', False)):
            self._path_invalid = True
            self.activeTransactionChanged.emit()
            return True
        if transaction.draft.kind == MeasurementKind.CURVE:
            from qt_dicom_viewer.core.curve_geometry import curve_length_mm
            spacing = transaction.context.geometry.pixel_spacing
            transaction.draft.length_mm = curve_length_mm(transaction.draft.points, spacing.row, spacing.column)
        self._path_preview = None
        self._advance_angle_or_commit()
        return True

    def _creating_angle(self) -> bool:
        return (isinstance(self._active_transaction, CreateMeasurementTransaction)
                and isinstance(self._active_transaction.draft, AngleMeasurementDraft))

    def tap_at(self, point: ImagePoint | None, *, slice_index: int,
               endpoint_tolerance: float, line_tolerance: float,
               context: MeasureContext | None = None,
               viewport_point: Point | None = None) -> None:
        if point is not None and self._creating_path():
            self._append_path_point(point)
            return
        if point is not None and self._creating_angle():
            self._update_point(point)
            self._advance_angle_or_commit()
            return
        if self._active_transaction is not None:
            self.cancel_transaction()
        hit = (self.hit_test(point, slice_index=slice_index,
                            endpoint_tolerance=endpoint_tolerance, line_tolerance=line_tolerance,
                            viewport_point=viewport_point)
               if point is not None else None)
        if hit is None and point is not None and context is not None and context.measurement_kind in (MeasurementKind.ANGLE, MeasurementKind.FREEHAND, MeasurementKind.CURVE):
            self._path_preview = None
            self._begin_create_transaction(point=point, context=context)
        elif hit is not None:
            self.select(hit)
        else:
            self.clear_selection()

    def preview_at(self, point: ImagePoint | None) -> None:
        """角度两段之间的悬停只更新草稿；按住鼠标时仍由拖动事件负责。"""
        if self._creating_path() and point is not None:
            draft = self._active_transaction.draft
            candidate = self._path_preview_points(point)
            if (len(candidate) >= (3 if draft.kind == MeasurementKind.FREEHAND else 2)
                    and not self._valid_path_points(candidate, draft.kind, getattr(draft, 'smooth', False))):
                self._path_invalid = True
                self.activeTransactionChanged.emit()
                return
            self._path_invalid = False
            self._path_preview = point
            self.activeTransactionChanged.emit()
            return
        if self._creating_angle() and self._drag_reference is None and point is not None:
            self._update_point(point)

    def begin(self, position: PointerPosition, context: MeasureContext | None) -> None:
        if not isinstance(context, MeasureContext):
            raise TypeError("MeasurementController requires MeasureContext")
        if self._geometry_only:
            context = replace(context, modality_pixels=None)
        point = position.image
        if point is None:
            return
        if self._creating_path():
            self._append_path_point(point)
            return
        if not (self._creating_angle() and context.measurement_kind == MeasurementKind.ANGLE):
            self.cancel_transaction()
            hit = self.hit_test(point, slice_index=context.slice_index,
                                endpoint_tolerance=context.endpoint_tolerance,
                                line_tolerance=context.line_tolerance,
                                viewport_point=position.viewport)
            if hit is None:
                self._begin_create_transaction(point=point, context=context)
            else:
                if self.presentation(hit.measurement_id)["locked"]:
                    self.select(hit)
                    return
                origin = self._label_origins.get(hit.measurement_id)
                linked = self._settings_controller.section("measurement")["linkLabelToShape"]
                if hit.target.kind == EditTargetKind.LABEL and not linked:
                    self._label_drag = (hit.measurement_id, point,
                        origin or point, self._label_positions.get(hit.measurement_id))
                    self.select(hit)
                    return
                if linked and origin is not None:
                    self._linked_label_reference = (hit.measurement_id, origin,
                        self._measurements[hit.measurement_id].points,
                        self._label_positions.get(hit.measurement_id))
                elif origin is not None:
                    self._label_positions.setdefault(hit.measurement_id, origin)
                self._begin_edit_transaction(hit=hit, context=context)
        if self._active_transaction is not None:
            self._drag_reference = replace(self._active_transaction.draft,
                                           points=list(self._active_transaction.draft.points))
            self._drag_start = position

    def _move_label(self, point):
        if self._label_drag is None or point is None:
            return
        uid, start, origin, _ = self._label_drag
        if not all(math.isfinite(v) for v in (point.column, point.row)):
            return
        self._label_positions[uid] = ImagePoint(
            origin.column + point.column - start.column,
            origin.row + point.row - start.row)
        self.measurementsChanged.emit()

    def update(self, drag_event: DragUpdateEvent) -> None:
        if self._label_drag is not None:
            self._move_label(drag_event.current_position.image)
            return
        transaction = self._active_transaction
        if transaction is None:
            return
        if self._creating_path():
            self.preview_at(drag_event.current_position.image)
            return
        candidate = self._operation(transaction.draft).update_draft(
            draft=self._drag_reference or transaction.draft,
            target=transaction.target, drag_event=drag_event, context=transaction.context,
        )
        if (getattr(candidate, 'kind', None) in (MeasurementKind.FREEHAND, MeasurementKind.CURVE)
                and not self._valid_path_points(candidate.points, candidate.kind,
                                                getattr(candidate, 'smooth', False))):
            return  # Keep the last valid draft and metric card during an invalid drag.
        transaction.draft = candidate
        if self._creating_angle() and transaction.target.index == AnglePointIndex.VERTEX:
            transaction.draft.points[2] = transaction.draft.points[1]
        if self._linked_label_reference is not None:
            uid, origin, before, _ = self._linked_label_reference
            after = transaction.draft.points
            dx = sum(p.column for p in after)/len(after) - sum(p.column for p in before)/len(before)
            dy = sum(p.row for p in after)/len(after) - sum(p.row for p in before)/len(before)
            self._label_positions[uid] = ImagePoint(origin.column+dx, origin.row+dy)
        self.activeTransactionChanged.emit()

    def _update_point(self, point: ImagePoint) -> None:
        position = PointerPosition(Point(point.column, point.row), point)
        self.update(DragUpdateEvent(self._drag_start or position, position, Offset(0, 0), Offset(0, 0)))

    def end(self, position: PointerPosition) -> None:
        if self._label_drag is not None:
            self._move_label(position.image)
            self._label_drag = None
            return
        if self._active_transaction is None:
            return
        if self._creating_path():
            self._drag_reference = None
            self._drag_start = None
            return
        # 松开位置可能比最后一次 move 更新，必须采纳 release 的坐标。
        if position.image is not None:
            self._update_point(position.image)
        self._drag_reference = None
        self._drag_start = None
        self._advance_angle_or_commit()

    def _advance_angle_or_commit(self) -> None:
        transaction = self._active_transaction
        if (isinstance(transaction, CreateMeasurementTransaction)
                and getattr(transaction.draft, 'kind', None) == MeasurementKind.FREEHAND):
            from qt_dicom_viewer.core.measurement_geometry import roi_metrics
            points = transaction.draft.points
            if len(points)>2 and point_distance(points[0],points[-1]) < 0.5: points.pop()
            spacing = transaction.context.geometry.pixel_spacing
            transaction.draft.metrics = roi_metrics(points, MeasurementKind.FREEHAND,
                transaction.context.modality_pixels, row_spacing=spacing.row,
                column_spacing=spacing.column, unit=transaction.context.pixel_unit, smooth=transaction.draft.smooth)
        if self._creating_angle() and transaction.target.index == AnglePointIndex.VERTEX:
            if point_distance(transaction.draft.points[0], transaction.draft.points[1]) <= 1e-6:
                return
            transaction.target = MeasurementEditTarget(EditTargetKind.CONTROL_POINT, AnglePointIndex.END)
            self.activeTransactionChanged.emit()
            return
        operation = self._operation(transaction.draft)
        measurement = operation.commit(transaction.draft)
        valid = operation.is_valid(measurement)
        if self._geometry_only and isinstance(measurement, RoiMeasurement):
            # 服务 ROI 可先保存几何，真实间距无效时由分析层给出明确错误。
            a, b = measurement.points
            valid = (all(math.isfinite(v) for v in (a.column, a.row, b.column, b.row))
                     and abs(a.column - b.column) >= 1e-3 and abs(a.row - b.row) >= 1e-3)
        if not valid:
            if not self._creating_angle():
                self.cancel_transaction()
            return
        if self._max_per_frame is not None and measurement.measurement_id not in self._measurements:
            same_frame = [m for m in self._measurements.values() if self._visible(m)]
            for old in same_frame[:max(0, len(same_frame) - self._max_per_frame + 1)]:
                self._measurements.pop(old.measurement_id)
                self._measurement_frames.pop(old.measurement_id, None)
                self._presentation.pop(old.measurement_id, None)
                self._sources.pop(old.measurement_id, None)
                self._label_positions.pop(old.measurement_id, None)
        self._linked_label_reference = None
        if measurement.measurement_id not in self._measurements:
            self._presentation[measurement.measurement_id] = dict(name="", hidden=False, locked=False,
                ordinal=1 + max((v.get("ordinal", 0) for v in self._presentation.values()), default=0))
        self._measurements[measurement.measurement_id] = measurement
        self._measurement_frames[measurement.measurement_id] = self._frame_key
        self._sources[measurement.measurement_id] = dict(self.current_source)
        self._selected_measurement_id = measurement.measurement_id
        self._selected_measurement_state = "completed"
        self._active_transaction = None
        self._drag_reference = None
        self._drag_start = None
        self.measurementsChanged.emit()
        self.activeTransactionChanged.emit()
        self.selectionChanged.emit()
        self.measurementCommitted.emit(measurement)

    def commit_service_rectangle(self, points: list[ImagePoint], context: MeasureContext) -> bool:
        """Submit validated service geometry through the same commit path as drawing."""
        if (not self._geometry_only or self.has_active_transaction
                or context.measurement_kind != MeasurementKind.RECT or len(points) != 2):
            return False
        self._begin_create_transaction(point=points[0], context=context)
        self._active_transaction.draft.points = points
        self._advance_angle_or_commit()
        return self._selected_measurement_state == "completed"

    def selected_copy(self) -> dict | None:
        measurement = self._measurements.get(self._selected_measurement_id)
        if self.has_active_transaction or measurement is None or not self._visible(measurement):
            return None
        kind = "angle" if isinstance(measurement, AngleMeasurement) else measurement.kind.value
        payload = {"kind": kind, "points": [[p.column, p.row] for p in measurement.points]}
        if isinstance(measurement, RoiMeasurement) and measurement.kind == MeasurementKind.FREEHAND:
            payload["smooth"] = measurement.smooth
        return payload

    def paste_points(self, points: list[ImagePoint], context: MeasureContext, *, smooth: bool | None = None) -> str:
        if self.has_active_transaction:
            return ""
        operation = {MeasurementKind.LENGTH: self._length_operation,
                      MeasurementKind.CURVE: self._length_operation,
                     MeasurementKind.ARROW: self._length_operation,
                     MeasurementKind.ANGLE: self._angle_operation,
                     MeasurementKind.RECT: self._roi_operation,
                     MeasurementKind.FREEHAND: self._roi_operation,
                     MeasurementKind.ELLIPSE: self._roi_operation}[context.measurement_kind]
        draft = operation.create_draft(point=points[0], context=context)
        draft.points = points
        if isinstance(draft, RoiMeasurementDraft) and smooth is not None:
            draft.smooth = smooth
        position = PointerPosition(Point(0, 0), points[0])
        # A zero translation recomputes length, angle or ROI statistics on the target frame.
        draft = operation.update_draft(draft=draft,
            target=MeasurementEditTarget(EditTargetKind.OUTLINE),
            drag_event=DragUpdateEvent(position, position, Offset(0, 0), Offset(0, 0)), context=context)
        measurement = operation.commit(draft)
        if not operation.is_valid(measurement):
            return ""
        if measurement.measurement_id not in self._measurements:
            self._presentation[measurement.measurement_id] = dict(name="", hidden=False, locked=False,
                ordinal=1 + max((v.get("ordinal", 0) for v in self._presentation.values()), default=0))
        self._measurements[measurement.measurement_id] = measurement
        self._measurement_frames[measurement.measurement_id] = self._frame_key
        self._sources[measurement.measurement_id] = dict(self.current_source)
        self.measurementsChanged.emit()
        self.select_completed(measurement.measurement_id)
        self.measurementCommitted.emit(measurement)
        return measurement.measurement_id

    def select_completed(self, measurement_id: str) -> None:
        if measurement_id in self._measurements:
            self._selected_measurement_id = measurement_id
            self._selected_measurement_state = "completed"
            self.selectionChanged.emit()

    def cancel_transaction(self) -> None:
        if self._linked_label_reference is not None:
            uid, _, _, old = self._linked_label_reference
            if old is None:
                self._label_positions.pop(uid, None)
            else:
                self._label_positions[uid] = old
            self._linked_label_reference = None
        if self._label_drag is not None:
            uid, _, _, old = self._label_drag
            if old is None:
                self._label_positions.pop(uid, None)
            else:
                self._label_positions[uid] = old
            self._label_drag = None
            self.measurementsChanged.emit()
        transaction = self._active_transaction
        if transaction is None:
            return
        self._selected_measurement_id = (transaction.draft.measurement_id
                                         if isinstance(transaction, EditMeasurementTransaction) else None)
        self._selected_measurement_state = (self._selection_before_edit
                                           if self._selected_measurement_id else "none")
        self._active_transaction = None
        self._drag_reference = None
        self._drag_start = None
        self.measurementsChanged.emit()
        self.activeTransactionChanged.emit()
        self.selectionChanged.emit()

    def clear_selection(self) -> None:
        if self._selected_measurement_id is not None:
            self._selected_measurement_id = None
            self._selected_measurement_state = "none"
            self.selectionChanged.emit()

    def clear_all(self) -> None:
        self._linked_label_reference = None
        self._label_drag = None
        self._label_positions.clear()
        self._label_origins.clear()
        self._measurements.clear()
        self._presentation.clear()
        self._sources.clear()
        self._measurement_frames.clear()
        self._active_transaction = None
        self._drag_reference = None
        self._drag_start = None
        self._selected_measurement_id = None
        self._selected_measurement_state = "none"
        self.measurementsChanged.emit()
        self.activeTransactionChanged.emit()
        self.selectionChanged.emit()


    def refresh_roi_metrics(self, pixels, frame) -> None:
        """Refresh matching-plane ROI statistics and repaired curve arc lengths."""
        from qt_dicom_viewer.core.measurement_geometry import roi_metrics
        if pixels is None:
            return
        changed = False
        for measurement in self.visible_measurements:
            if isinstance(measurement, LengthMeasurement) and measurement.kind == MeasurementKind.CURVE:
                from qt_dicom_viewer.core.curve_geometry import curve_length_mm
                spacing = frame.geometry.pixel_spacing
                length = curve_length_mm(measurement.points, spacing.row, spacing.column)
                self._measurements[measurement.measurement_id] = replace(measurement, length_mm=length)
                changed = True
                continue
            if not isinstance(measurement, RoiMeasurement):
                continue
            metrics = roi_metrics(measurement.points, measurement.kind, pixels,
                                  row_spacing=frame.geometry.pixel_spacing.row,
                                  column_spacing=frame.geometry.pixel_spacing.column,
                                  unit=frame.pixel_value_meta.unit, smooth=measurement.smooth)
            self._measurements[measurement.measurement_id] = replace(measurement, metrics=metrics)
            changed = True
        if changed:
            self.measurementsChanged.emit()
    def clear_kind(self, *, arrows: bool) -> None:
        self.cancel_transaction()
        self.clear_selection()
        for key, measurement in list(self._measurements.items()):
            if (getattr(measurement, "kind", None) == MeasurementKind.ARROW) == arrows:
                del self._measurements[key]
                self._measurement_frames.pop(key, None)
                self._presentation.pop(key, None)
                self._sources.pop(key, None)
                self._label_positions.pop(key, None)
        self.measurementsChanged.emit()

    def delete_selected(self) -> None:
        self.cancel_transaction()
        if self._selected_measurement_id is not None:
            self.delete_measurement(self._selected_measurement_id)

    def select(self, hit: MeasurementHit) -> None:
        if hit.measurement_id in self._measurements and (
                hit.measurement_id != self._selected_measurement_id
                or self._selected_measurement_state != "draft"):
            self._selected_measurement_id = hit.measurement_id
            self._selected_measurement_state = "draft"
            self.selectionChanged.emit()

    @Slot("QVariantList")
    def setLabelHitRegions(self, regions: list[dict]) -> None:
        """输入事件前接收 QML 实际标签矩形；整体替换，避免保留已经移走的标签。"""
        self._label_regions.clear()
        self._label_origins.clear()
        for region in regions:
            try:
                label = MeasurementLabelRegion(
                    measurement_id=str(region["measurementId"]),
                    x=float(region["x"]), y=float(region["y"]),
                    width=float(region["width"]), height=float(region["height"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._label_regions[label.measurement_id] = label
            try:
                column, row = float(region["labelColumn"]), float(region["labelRow"])
                if math.isfinite(column) and math.isfinite(row):
                    self._label_origins[label.measurement_id] = ImagePoint(column, row)
            except (KeyError, TypeError, ValueError):
                pass

    def _hit_test_candidates(self, slice_index: int) -> list[Measurement]:
        """只检测当前切面；距离相同时优先选中项，其次是后绘制的图形。"""
        candidates = [
            measurement for measurement in reversed(tuple(self._measurements.values()))
            if measurement.slice_index == slice_index and self._visible(measurement)
        ]
        return sorted(candidates, key=lambda measurement:
                      measurement.measurement_id != self._selected_measurement_id)

    def _hit_tolerances(self, measurement: Measurement,
                        endpoint_tolerance: float,
                        line_tolerance: float) -> tuple[float, float]:
        if not self._adaptive_roi_hit_tolerance or not isinstance(measurement, RoiMeasurement):
            return endpoint_tolerance, line_tolerance
        first = ImagePoint(min(p.column for p in measurement.points), min(p.row for p in measurement.points))
        opposite = ImagePoint(max(p.column for p in measurement.points), max(p.row for p in measurement.points))
        short_side = min(
            abs(first.column - opposite.column),
            abs(first.row - opposite.row),
        )
        return (
            min(endpoint_tolerance, short_side / 3),
            min(line_tolerance, short_side / 4),
        )

    def hit_test(
        self,
        point: ImagePoint,
        *,
        slice_index: int,
        endpoint_tolerance: float,
        line_tolerance: float,
        viewport_point: Point | None = None,
    ) -> MeasurementHit | None:
        """按部位优先级选择命中，不在这里执行编辑动作。

        顺序：控制点 > 标签 > 轮廓 > ROI 内部。是否选中不影响内部是否命中。
        point 和两个容差使用图像像素；viewport_point 仅用于标签的视口矩形。
        返回 target.kind 标明部位，target.index 标明控制点/直线边编号。
        """
        measurements = self._hit_test_candidates(slice_index)

        # 1. 控制点负责调整形状，优先于其附近的轮廓和标签。
        control_hit = nearest_hit(
            hit_test_control_points(
                measurement,
                point,
                self._hit_tolerances(
                    measurement, endpoint_tolerance, line_tolerance,
                )[0],
            )
            for measurement in measurements
        )
        if control_hit is not None:
            return control_hit

        # 2. 标签按屏幕矩形包含关系判断，不与图像像素距离混算。
        if viewport_point is not None:
            for measurement in measurements:
                region = self._label_regions.get(measurement.measurement_id)
                if region is not None:
                    label_hit = hit_test_label(region, viewport_point)
                    if label_hit is not None:
                        return label_hit

        # 3. 所有图形统一叫 OUTLINE；矩形边不再被误称为 BODY。
        outline_hit = nearest_hit(
            hit_test_outline(
                measurement,
                point,
                self._hit_tolerances(
                    measurement, endpoint_tolerance, line_tolerance,
                )[1],
            )
            for measurement in measurements
        )
        if outline_hit is not None:
            return outline_hit

        # 4. 内部命中与选择状态无关，否则未选中 ROI 无法通过内部点击被选中。
        # 多个 ROI 重叠时，沿用选中项优先、其次后绘制项优先的候选顺序。
        for measurement in measurements:
            interior_hit = hit_test_interior(measurement, point)
            if interior_hit is not None:
                return interior_hit
        return None

    def _begin_create_transaction(self, *, point: ImagePoint, context: MeasureContext) -> None:
        operations = {MeasurementKind.LENGTH: self._length_operation,
                      MeasurementKind.CURVE: self._length_operation,
                      MeasurementKind.ARROW: self._length_operation,
                      MeasurementKind.ANGLE: self._angle_operation,
                      MeasurementKind.RECT: self._roi_operation,
                      MeasurementKind.FREEHAND: self._roi_operation,
                      MeasurementKind.ELLIPSE: self._roi_operation}
        self._path_invalid = False
        self._path_preview = None
        draft = operations[context.measurement_kind].create_draft(point=point, context=context)
        endpoint = 2 if isinstance(draft, RoiMeasurementDraft) else 1
        self._active_transaction = CreateMeasurementTransaction(
            context=context, draft=draft,
            target=MeasurementEditTarget(EditTargetKind.CONTROL_POINT, endpoint),
        )
        self._selected_measurement_id = None
        self._selected_measurement_state = "none"
        self.activeTransactionChanged.emit()
        self.selectionChanged.emit()

    def _begin_edit_transaction(self, *, hit: MeasurementHit, context: MeasureContext) -> None:
        measurement = self._measurements[hit.measurement_id]
        draft = self._operation(measurement).create_edit_draft(measurement)
        self._selection_before_edit = (self._selected_measurement_state
                                       if self._selected_measurement_id == measurement.measurement_id
                                       else "completed")
        self._selected_measurement_id = measurement.measurement_id
        self._selected_measurement_state = "draft"
        self._active_transaction = EditMeasurementTransaction(context=context, draft=draft, target=hit.target)
        # 编辑期间只显示草稿，提交或取消后再恢复正式图形。
        self.measurementsChanged.emit()
        self.activeTransactionChanged.emit()
        self.selectionChanged.emit()
