"""三点角度测量的无状态操作，第二个点始终作为顶点。"""

import math
from dataclasses import replace
from uuid import uuid4

from voxplane.core.measurement_geometry import angle_degrees, edited_points
from voxplane.model import (
    AngleMeasurement,
    AngleMeasurementDraft,
    DragUpdateEvent,
    ImagePoint,
    MeasureContext,
    MeasurementEditTarget,
)


class AngleMeasureOperation:
    def create_draft(
        self,
        *,
        point: ImagePoint,
        context: MeasureContext,
    ) -> AngleMeasurementDraft:
        return AngleMeasurementDraft(
            measurement_id=str(uuid4()),
            series_uid=context.series_uid,
            sop_instance_uid=context.sop_instance_uid,
            slice_index=context.slice_index,
            points=[point, point, point],
            angle=math.nan,
        )

    def create_edit_draft(
        self,
        measurement: AngleMeasurement,
    ) -> AngleMeasurementDraft:
        return AngleMeasurementDraft(
            measurement_id=measurement.measurement_id,
            series_uid=measurement.series_uid,
            sop_instance_uid=measurement.sop_instance_uid,
            slice_index=measurement.slice_index,
            points=list(measurement.points),
            angle=measurement.angle,
        )

    def update_draft(
        self,
        *,
        draft: AngleMeasurementDraft,
        target: MeasurementEditTarget,
        drag_event: DragUpdateEvent,
        context: MeasureContext,
    ) -> AngleMeasurementDraft:
        points = edited_points(draft.points, target, drag_event)
        spacing = context.geometry.pixel_spacing
        angle = angle_degrees(points, row_spacing=spacing.row, column_spacing=spacing.column)
        # 缺少有效间距或边长为零时不能伪装成合法的零度角。
        return replace(draft, points=points, angle=math.nan if angle is None else angle)

    @staticmethod
    def commit(
        draft: AngleMeasurementDraft,
    ) -> AngleMeasurement:
        return AngleMeasurement(
            measurement_id=draft.measurement_id,
            series_uid=draft.series_uid,
            sop_instance_uid=draft.sop_instance_uid,
            slice_index=draft.slice_index,
            points=tuple(draft.points),
            angle=draft.angle,
        )

    @staticmethod
    def is_valid(measurement: AngleMeasurement) -> bool:
        return (math.isfinite(measurement.angle)
                and angle_degrees(measurement.points, row_spacing=1, column_spacing=1) is not None)
