"""按命中部位拆分的纯几何判断；选择优先级和可见性由控制器负责。"""

import math
from collections.abc import Iterable, Iterator

from voxplane.core.geometry_2d import point_distance, point_to_segment_distance
from voxplane.core.measurement_geometry import roi_corners
from voxplane.core.freehand_roi import contains_point, roi_outline
from voxplane.model.image_geometry import ImagePoint, Point
from voxplane.model.measure import (
    EditTargetKind,
    Measurement,
    MeasurementEditTarget,
    MeasurementHit,
    MeasurementKind,
    MeasurementLabelRegion,
    RoiMeasurement,
)


ELLIPSE_OUTLINE_SEGMENTS = 128


def nearest_hit(hits: Iterable[MeasurementHit | None]) -> MeasurementHit | None:
    """只比较同一部位的候选；距离相同保留输入顺序，由调用方决定叠放顺序。"""
    return min((hit for hit in hits if hit is not None), key=lambda hit: hit.distance, default=None)


def hit_test_control_points(
    measurement: Measurement,
    point: ImagePoint,
    tolerance: float,
) -> MeasurementHit | None:
    """命中可调整形状的控制点；椭圆控制点是包围盒角点，不是曲线上的点。"""
    control_points = roi_corners(measurement.points) if isinstance(measurement, RoiMeasurement) and measurement.kind != MeasurementKind.FREEHAND else measurement.points
    hits = []
    for control_index, control_point in enumerate(control_points):
        distance = point_distance(point, control_point)
        if distance <= tolerance:
            hits.append(MeasurementHit(
                measurement.measurement_id,
                MeasurementEditTarget(EditTargetKind.CONTROL_POINT, control_index),
                distance,
            ))
    return nearest_hit(hits)


def _outline_segments(measurement: Measurement) -> Iterator[tuple[int | None, ImagePoint, ImagePoint]]:
    """返回（直线边编号，边起点，边终点）；仅 ROI 闭合，角度不能连起点和终点。"""
    if not isinstance(measurement, RoiMeasurement):
        points = measurement.points
        if getattr(measurement, "kind", None) == MeasurementKind.CURVE:
            from voxplane.core.curve_geometry import sample_curve
            points = sample_curve(points)
        for edge_index, (start, end) in enumerate(zip(points, points[1:])):
            yield edge_index, start, end
        return

    if measurement.kind in (MeasurementKind.RECT, MeasurementKind.FREEHAND):
        corners = roi_outline(measurement.points, measurement.smooth) if measurement.kind == MeasurementKind.FREEHAND else roi_corners(measurement.points)
        for edge_index in range(len(corners)):
            yield edge_index, corners[edge_index], corners[(edge_index + 1) % len(corners)]
        return

    # 保留折线近似检测椭圆轮廓；采样小段不是可编辑的“边”，不能暴露为业务编号。
    first, opposite = measurement.points
    center_x = (first.column + opposite.column) / 2
    center_y = (first.row + opposite.row) / 2
    radius_x = abs(first.column - opposite.column) / 2
    radius_y = abs(first.row - opposite.row) / 2
    outline_points = [
        ImagePoint(
            center_x + radius_x * math.cos(sample * math.tau / ELLIPSE_OUTLINE_SEGMENTS),
            center_y + radius_y * math.sin(sample * math.tau / ELLIPSE_OUTLINE_SEGMENTS),
        )
        for sample in range(ELLIPSE_OUTLINE_SEGMENTS)
    ]
    for sample in range(ELLIPSE_OUTLINE_SEGMENTS):
        yield None, outline_points[sample], outline_points[(sample + 1) % ELLIPSE_OUTLINE_SEGMENTS]


def hit_test_outline(
    measurement: Measurement,
    point: ImagePoint,
    tolerance: float,
) -> MeasurementHit | None:
    """只判断鼠标到轮廓的距离，不把图形内部当作轮廓。"""
    hits = []
    for edge_index, edge_start, edge_end in _outline_segments(measurement):
        distance = point_to_segment_distance(point, edge_start, edge_end)
        if distance <= tolerance:
            hits.append(MeasurementHit(
                measurement.measurement_id,
                MeasurementEditTarget(EditTargetKind.OUTLINE, edge_index),
                distance,
            ))
    return nearest_hit(hits)


def hit_test_interior(measurement: Measurement, point: ImagePoint) -> MeasurementHit | None:
    """只判断 ROI 的开区域内部；长度和角度没有可命中的内部区域。"""
    if not isinstance(measurement, RoiMeasurement):
        return None
    if measurement.kind == MeasurementKind.FREEHAND:
        return (MeasurementHit(measurement.measurement_id, MeasurementEditTarget(EditTargetKind.INTERIOR), 0.0)
                if contains_point(roi_outline(measurement.points, measurement.smooth), point.column, point.row) else None)
    first, opposite = measurement.points
    left, right = sorted((first.column, opposite.column))
    top, bottom = sorted((first.row, opposite.row))
    if not (left < point.column < right and top < point.row < bottom):
        return None
    if measurement.kind == MeasurementKind.ELLIPSE:
        center_x, center_y = (left + right) / 2, (top + bottom) / 2
        radius_x, radius_y = (right - left) / 2, (bottom - top) / 2
        normalized_distance = ((point.column - center_x) / radius_x) ** 2 + ((point.row - center_y) / radius_y) ** 2
        if normalized_distance >= 1:
            return None
    return MeasurementHit(measurement.measurement_id, MeasurementEditTarget(EditTargetKind.INTERIOR), 0.0)


def hit_test_label(region: MeasurementLabelRegion, viewport_point: Point) -> MeasurementHit | None:
    """仅用标签实际视口矩形判断；字号、换行和缩放后的布局由 QML 决定。"""
    if not all(math.isfinite(value) for value in (
        region.x, region.y, region.width, region.height, viewport_point.x, viewport_point.y,
    )) or region.width <= 0 or region.height <= 0:
        return None
    if (region.x <= viewport_point.x <= region.x + region.width
            and region.y <= viewport_point.y <= region.y + region.height):
        return MeasurementHit(region.measurement_id, MeasurementEditTarget(EditTargetKind.LABEL), 0.0)
    return None
