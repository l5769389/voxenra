"""矩形和椭圆按包围盒编辑；自由形状按顶点和闭合轮廓计算。"""

import math
from dataclasses import replace
from uuid import uuid4

from voxplane.core.measurement_geometry import edited_points, roi_corners, roi_metrics
from voxplane.model.image_geometry import DragUpdateEvent, ImagePoint
from voxplane.model.measure import (
    EditTargetKind, MeasureContext, MeasurementEditTarget,
    RoiMeasurement, RoiMeasurementDraft, RoiMetrics, MeasurementKind,
)


class RoiMeasureOperation:
    def __init__(self, *, physical_square: bool = False):
        self._physical_square = physical_square

    @staticmethod
    def _square_corner(anchor: ImagePoint, point: ImagePoint,
                       row_spacing: float, column_spacing: float) -> ImagePoint:
        """以 anchor 为固定角，将拖动点约束为物理尺寸正方形的对角。"""
        if not all(math.isfinite(value) and value > 0
                   for value in (row_spacing, column_spacing)):
            return point
        delta_column = point.column - anchor.column
        delta_row = point.row - anchor.row
        # 取较短的物理方向，使约束后的方框始终位于用户拖出的范围内，
        # 不会因为各向异性像素间距而越过指针或图像边界。
        side_mm = min(abs(delta_column) * column_spacing,
                      abs(delta_row) * row_spacing)
        column_sign = -1 if delta_column < 0 else 1
        row_sign = -1 if delta_row < 0 else 1
        return ImagePoint(
            column=anchor.column + column_sign * side_mm / column_spacing,
            row=anchor.row + row_sign * side_mm / row_spacing,
        )

    def create_draft(self, *, point: ImagePoint, context: MeasureContext) -> RoiMeasurementDraft:
        return RoiMeasurementDraft(
            measurement_id=str(uuid4()), series_uid=context.series_uid,
            sop_instance_uid=context.sop_instance_uid, slice_index=context.slice_index,
            smooth=context.measurement_kind == MeasurementKind.FREEHAND,
            kind=context.measurement_kind, points=[point] if context.measurement_kind == MeasurementKind.FREEHAND else [point, point], metrics=RoiMetrics(unit=context.pixel_unit),
        )

    def create_edit_draft(self, measurement: RoiMeasurement) -> RoiMeasurementDraft:
        return RoiMeasurementDraft(
            measurement_id=measurement.measurement_id, series_uid=measurement.series_uid,
            sop_instance_uid=measurement.sop_instance_uid, slice_index=measurement.slice_index,
            kind=measurement.kind, points=list(measurement.points), metrics=measurement.metrics, smooth=measurement.smooth,
        )

    def update_draft(self, *, draft: RoiMeasurementDraft, target: MeasurementEditTarget,
                     drag_event: DragUpdateEvent, context: MeasureContext) -> RoiMeasurementDraft:
        point = drag_event.current_position.image
        if point is None:
            return draft
        if draft.kind != MeasurementKind.FREEHAND and target.kind == EditTargetKind.CONTROL_POINT and target.index in range(4):
            opposite = roi_corners(draft.points)[(target.index + 2) % 4]
            if self._physical_square:
                spacing = context.geometry.pixel_spacing
                point = self._square_corner(
                    opposite, point, spacing.row, spacing.column
                )
            points = [opposite, point]
        else:
            points = edited_points(draft.points, target, drag_event)
        spacing = context.geometry.pixel_spacing
        metrics = roi_metrics(points, draft.kind, context.modality_pixels,
                              row_spacing=spacing.row, column_spacing=spacing.column,
                              unit=context.pixel_unit, smooth=draft.smooth)
        return replace(draft, points=points, metrics=metrics)

    @staticmethod
    def commit(draft: RoiMeasurementDraft) -> RoiMeasurement:
        return RoiMeasurement(
            measurement_id=draft.measurement_id, series_uid=draft.series_uid,
            sop_instance_uid=draft.sop_instance_uid, slice_index=draft.slice_index,
            kind=draft.kind, points=tuple(draft.points), metrics=draft.metrics, smooth=draft.smooth,
        )

    @staticmethod
    def is_valid(measurement: RoiMeasurement) -> bool:
        if measurement.kind == MeasurementKind.FREEHAND:
            from voxplane.core.freehand_roi import simple_polygon, roi_outline
            return simple_polygon(roi_outline(measurement.points, measurement.smooth)) and (measurement.metrics.area_mm2 or 0) > 0
        # 允许轮廓超出影像；没有有效像素时仍可测面积，但灰度统计显示为空。
        first, second = measurement.points
        return (abs(first.column - second.column) >= 1e-3
                and abs(first.row - second.row) >= 1e-3
                and measurement.metrics.area_mm2 is not None
                and measurement.metrics.area_mm2 > 0)
