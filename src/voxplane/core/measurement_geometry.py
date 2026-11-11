"""测量的纯数学部分，不依赖 Qt、视口或显示窗宽窗位。"""
from voxplane.i18n import message as _msg

import math
from collections.abc import Sequence

import numpy as np

from voxplane.model.image_geometry import DragUpdateEvent, ImagePoint
from voxplane.model.measure import EditTargetKind, MeasurementEditTarget, MeasurementKind, RoiMetrics
from voxplane.core.freehand_roi import polygon_area, polygon_mask, roi_outline


def valid_spacing(row_spacing: float | None, column_spacing: float | None) -> bool:
    return all(value is not None and math.isfinite(value) and value > 0
               for value in (row_spacing, column_spacing))


def angle_degrees(points: Sequence[ImagePoint], *, row_spacing: float,
                  column_spacing: float) -> float | None:
    """在物理平面内求三点夹角，第二点是顶点，范围为 0～180 度。"""
    if len(points) != 3 or not valid_spacing(row_spacing, column_spacing):
        return None
    start, vertex, end = points
    ax = (start.column - vertex.column) * column_spacing
    ay = (start.row - vertex.row) * row_spacing
    bx = (end.column - vertex.column) * column_spacing
    by = (end.row - vertex.row) * row_spacing
    if not all(math.isfinite(v) for v in (ax, ay, bx, by)):
        return None
    if min(math.hypot(ax, ay), math.hypot(bx, by)) <= 1e-9:
        return None
    return math.degrees(math.atan2(abs(ax * by - ay * bx), ax * bx + ay * by))


def edited_points(points: Sequence[ImagePoint], target: MeasurementEditTarget,
                  event: DragUpdateEvent) -> list[ImagePoint]:
    """从拖动开始时的点集计算新位置，避免多次更新累积平移误差。"""
    result = list(points)
    current = event.current_position.image
    start = event.start_position.image
    if current is None:
        return result
    if target.kind == EditTargetKind.CONTROL_POINT and target.index is not None:
        if 0 <= target.index < len(result):
            result[target.index] = current
    elif target.kind in (EditTargetKind.OUTLINE, EditTargetKind.INTERIOR, EditTargetKind.LABEL) and start is not None:
        # 三种命中部位都执行整体平移，但命中结果仍保留各自部位，不能混称为 BODY。
        dx, dy = current.column - start.column, current.row - start.row
        result = [ImagePoint(p.column + dx, p.row + dy) for p in points]
    return result


def roi_corners(points: Sequence[ImagePoint]) -> tuple[ImagePoint, ...]:
    """由两个对角点得到四个角点，保持固定顺序供绘制和命中测试共用。"""
    first, second = points
    return (first, ImagePoint(second.column, first.row),
            second, ImagePoint(first.column, second.row))


def roi_metrics(points: Sequence[ImagePoint], kind: MeasurementKind, pixels: np.ndarray | None, *,
                row_spacing: float, column_spacing: float, unit: str = "", smooth: bool = False) -> RoiMetrics:
    """按像素中心是否落入形状采样；标准差使用总体定义（ddof=0）。"""
    if kind not in (MeasurementKind.RECT, MeasurementKind.ELLIPSE, MeasurementKind.FREEHAND):
        raise ValueError(_msg('text.0094'))
    freehand = kind == MeasurementKind.FREEHAND
    if freehand:
        points = roi_outline(points, smooth)
    if (len(points) < 3 if freehand else len(points) != 2) or not all(math.isfinite(v) for p in points for v in (p.column, p.row)):
        return RoiMetrics(unit=unit)
    left, right = min(p.column for p in points), max(p.column for p in points)
    top, bottom = min(p.row for p in points), max(p.row for p in points)
    width, height = right - left, bottom - top
    dimensions = {}
    if valid_spacing(row_spacing, column_spacing):
        w, h = width * column_spacing, height * row_spacing
        area = w * h * (math.pi / 4 if kind == MeasurementKind.ELLIPSE else 1)
        if freehand: area = polygon_area(points) * row_spacing * column_spacing
        if all(math.isfinite(v) for v in (w, h, area)):
            dimensions = dict(width_mm=w, height_mm=h, area_mm2=area)
            if freehand:
                dimensions['perimeter_mm'] = sum(math.hypot((a.column-b.column)*column_spacing,
                    (a.row-b.row)*row_spacing) for a,b in zip(points, (*points[1:],points[0])))
    empty = RoiMetrics(**dimensions, unit=unit)
    if pixels is None or pixels.ndim != 2 or width <= 0 or height <= 0:
        return empty
    rows, columns = pixels.shape
    # 先裁剪包围盒再分配掩膜，即使轮廓远超画布也不会分配巨大数组。
    x0, x1 = max(0, math.ceil(left)), min(columns - 1, math.floor(right))
    y0, y1 = max(0, math.ceil(top)), min(rows - 1, math.floor(bottom))
    if x0 > x1 or y0 > y1:
        return empty
    values = pixels[y0:y1 + 1, x0:x1 + 1]
    mask = np.isfinite(values)
    if freehand:
        mask &= polygon_mask(points, x0, x1, y0, y1)
    if kind == MeasurementKind.ELLIPSE:
        yy, xx = np.ogrid[y0:y1 + 1, x0:x1 + 1]
        mask = mask & (((xx - (left + right) / 2) / (width / 2)) ** 2
                       + ((yy - (top + bottom) / 2) / (height / 2)) ** 2 <= 1 + 1e-12)
    selected = values[mask].astype(np.float64)
    if selected.size == 0:
        return empty
    return RoiMetrics(**dimensions, pixel_count=int(selected.size),
                      mean=float(selected.mean()), std=float(selected.std(ddof=0)),
                      minimum=float(selected.min()), maximum=float(selected.max()), unit=unit)
