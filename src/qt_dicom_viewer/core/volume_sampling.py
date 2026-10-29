"""Shared finite-weight trilinear sampling in (slice, row, column) coordinates.

Callers bound the coordinate arrays, not the source volume. Missing neighbours
are renormalized; points outside voxel-center bounds remain NaN.
"""
from __future__ import annotations

import numpy as np


class VolumeSamplingError(RuntimeError):
    pass


def sample_volume(
    volume: np.ndarray,
    slice_coordinates: np.ndarray,
    row_coordinates: np.ndarray,
    column_coordinates: np.ndarray,
) -> np.ndarray:
    """对一组连续体素坐标执行三线性插值。"""

    if (volume.ndim != 3 or any(n == 0 for n in volume.shape)
            or volume.dtype.kind not in "fiu"):
        raise VolumeSamplingError(
            f"Expected a 3D volume, got shape={volume.shape}"
        )

    try:
        slice_coordinates, row_coordinates, column_coordinates = np.broadcast_arrays(
            np.asarray(slice_coordinates, dtype=np.float64),
            np.asarray(row_coordinates, dtype=np.float64),
            np.asarray(column_coordinates, dtype=np.float64))
    except (TypeError, ValueError, OverflowError) as error:
        raise VolumeSamplingError("Coordinates must be broadcastable numeric arrays") from error
    finite = (np.isfinite(slice_coordinates) & np.isfinite(row_coordinates)
              & np.isfinite(column_coordinates))
    slice_coordinates, row_coordinates, column_coordinates = (
        np.where(finite, coordinates, 0.) for coordinates in
        (slice_coordinates, row_coordinates, column_coordinates))

    slice_max, row_max, column_max = (
        size - 1 for size in volume.shape
    )
    epsilon = 1e-6
    # 倾斜 Volume 的矩形投影可能包含体数据之外的点。先记录有效性，
    # 再裁剪坐标以保证后续数组索引安全。
    valid = finite & (
        (slice_coordinates >= -epsilon)
        & (slice_coordinates <= slice_max + epsilon)
        & (row_coordinates >= -epsilon)
        & (row_coordinates <= row_max + epsilon)
        & (column_coordinates >= -epsilon)
        & (column_coordinates <= column_max + epsilon)
    )

    slices = np.clip(
        slice_coordinates,
        0,
        slice_max,
    )
    rows = np.clip(
        row_coordinates,
        0,
        row_max,
    )
    columns = np.clip(
        column_coordinates,
        0,
        column_max,
    )

    slice0 = np.floor(slices).astype(np.intp)
    # 三个轴上的向下和向上取整确定周围 8 个源体素；坐标的小数部分
    # 作为后续插值权重。
    row0 = np.floor(rows).astype(np.intp)
    column0 = np.floor(columns).astype(np.intp)
    slice1 = np.minimum(slice0 + 1, slice_max)
    row1 = np.minimum(row0 + 1, row_max)
    column1 = np.minimum(column0 + 1, column_max)

    slice_weight = slices - slice0
    row_weight = rows - row0
    column_weight = columns - column0

    if volume.flags.c_contiguous:
        # One flat index avoids rebuilding three-dimensional advanced
        # indices eight times. Boundary neighbours still clamp independently,
        # including volumes with a single voxel along an axis.
        flat = volume.reshape(-1)
        base = (slice0 * volume.shape[1] + row0) * volume.shape[2] + column0
        ds = (slice1 - slice0) * (volume.shape[1] * volume.shape[2])
        dr = (row1 - row0) * volume.shape[2]
        dc = column1 - column0
        values = (flat[base], flat[base + dc],
                  flat[base + dr], flat[base + dr + dc],
                  flat[base + ds], flat[base + ds + dc],
                  flat[base + ds + dr], flat[base + ds + dr + dc])
    else:
        # Transposed/strided data must not incur a whole-volume copy per plane.
        values = tuple(volume[s, r, c]
                       for s in (slice0, slice1)
                       for r in (row0, row1)
                       for c in (column0, column1))

    if all(np.isfinite(value).all() for value in values):
        # The usual CT/PET neighbourhood has no missing voxels. Separable
        # linear interpolation needs neither eight weight arrays nor a
        # validity denominator. Float64 weights preserve signed HU and tiny
        # PET values until the final float32 output, as in the masked path.
        row_values = tuple(a * (1 - column_weight) + b * column_weight
                           for a, b in zip(values[::2], values[1::2]))
        slice_values = tuple(a * (1 - row_weight) + b * row_weight
                             for a, b in zip(row_values[::2], row_values[1::2]))
        sampled = np.asarray(slice_values[0] * (1 - slice_weight)
                             + slice_values[1] * slice_weight, dtype=np.float32)
        sampled[~valid] = np.nan
        return np.ascontiguousarray(sampled)

    # Missing/non-finite neighbours retain the original finite-weight
    # renormalization; they must not turn valid tissue into black holes.
    numerator = np.zeros_like(slices, dtype=np.float64)
    denominator = np.zeros_like(slices, dtype=np.float64)
    for index, value in enumerate(values):
        weight = ((slice_weight if index & 4 else 1 - slice_weight)
                  * (row_weight if index & 2 else 1 - row_weight)
                  * (column_weight if index & 1 else 1 - column_weight))
        supported = np.isfinite(value) & (weight > 0)
        numerator += np.where(supported, value, 0) * weight
        denominator += np.where(supported, weight, 0)
    sampled = np.full(slices.shape, np.nan, dtype=np.float32)
    np.divide(numerator, denominator, out=sampled, where=denominator > 0)

    # Volume 之外的位置保留为缺失模态值；apply_window 会将其显示为背景。
    sampled[~valid] = np.nan
    return np.ascontiguousarray(sampled)

