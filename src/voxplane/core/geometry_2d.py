import math

from voxplane.model.image_geometry import ImagePoint


def point_distance(
    first: ImagePoint,
    second: ImagePoint,
) -> float:
    """返回两个图像点之间的欧氏距离，单位为像素。"""
    return math.hypot(
        first.column - second.column,
        first.row - second.row,
    )


def point_to_segment_distance(
    point: ImagePoint,
    start: ImagePoint,
    end: ImagePoint,
) -> float:
    """返回图像点到有限线段的最短距离，单位为像素。"""
    segment_column = end.column - start.column
    segment_row = end.row - start.row
    point_column = point.column - start.column
    point_row = point.row - start.row
    segment_length_squared = (
        segment_column * segment_column
        + segment_row * segment_row
    )

    if segment_length_squared == 0:
        return point_distance(point, start)

    projection = (
        point_column * segment_column
        + point_row * segment_row
    ) / segment_length_squared
    projection = max(0.0, min(1.0, projection))

    nearest_column = (
        start.column + projection * segment_column
    )
    nearest_row = start.row + projection * segment_row

    return math.hypot(
        point.column - nearest_column,
        point.row - nearest_row,
    )


def image_point_distance_mm(
    first: ImagePoint,
    second: ImagePoint,
    *,
    row_spacing: float | None,
    column_spacing: float | None,
) -> float | None:
    """按图像行列间距计算两点间物理距离，单位为 mm。"""
    if (
        row_spacing is None
        or column_spacing is None
        or not math.isfinite(row_spacing)
        or not math.isfinite(column_spacing)
        or row_spacing <= 0
        or column_spacing <= 0
    ):
        return None

    delta_column_mm = (
        second.column - first.column
    ) * column_spacing
    delta_row_mm = (
        second.row - first.row
    ) * row_spacing

    return math.hypot(
        delta_column_mm,
        delta_row_mm,
    )
