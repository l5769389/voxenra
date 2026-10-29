"""Bounded, cancellable straightened CPR and true perpendicular cross-sections.

The caller owns the volume's lifetime and must not mutate its pixels during a
request. This class neither accesses the mutable volume cache nor copies it.
GUI request generations and stale-result rejection belong to the future
controller, not this synchronous numerical kernel.
"""
from __future__ import annotations

from numbers import Integral

import numpy as np

from qt_dicom_viewer.core.cpr_geometry import sample_centerline
from qt_dicom_viewer.core.render_cancellation import check_render_cancelled
from qt_dicom_viewer.core.volume_sampling import sample_volume
from qt_dicom_viewer.model.cpr import (
    CprCenterline, CprCrossSection, CprError, CprPath, CprResult, CprSettings,
    MAX_AXIS_SAMPLES, MAX_OUTPUT_PIXELS, MAX_SLAB_SAMPLES, MAX_SAMPLE_WORK,
    readonly_array,
)
from qt_dicom_viewer.model.dicom_core import DicomVolume, MprFrame, MprImageGeometry


def _centered_offsets(width_mm: float, step_mm: float) -> np.ndarray:
    intervals = 2 * int(np.ceil(width_mm / (2 * step_mm)))
    if intervals + 1 > MAX_AXIS_SAMPLES:
        raise CprError(f"Image axis exceeds the {MAX_AXIS_SAMPLES} sample limit")
    return np.linspace(-width_mm / 2, width_mm / 2, intervals + 1)


def _volume_transform(volume: DicomVolume) -> tuple[np.ndarray, float]:
    """Validate the supplied volume before converting any patient coordinates."""
    pixels, geometry = volume.modality_pixels, volume.geometry
    if (not isinstance(pixels, np.ndarray) or pixels.ndim != 3
            or pixels.dtype.kind not in "fiu" or any(n == 0 for n in pixels.shape)
            or pixels.shape != (geometry.slice_count, geometry.rows, geometry.columns)):
        raise CprError("Volume pixels and geometry dimensions do not agree")
    spacing = np.array([geometry.slice_spacing, geometry.row_spacing, geometry.column_spacing])
    if not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise CprError("Volume spacing must be finite and positive")
    try:
        transform = geometry.voxel_to_patient
        if not np.isfinite(transform).all():
            raise CprError("Volume affine contains nonfinite coordinates")
        singular = np.linalg.svd(transform[:3, :3], compute_uv=False)
        if singular[-1] <= 0 or singular[0] / singular[-1] > 1e8:
            raise CprError("Volume directions do not define a stable spatial affine")
        inverse = np.linalg.inv(transform)
        if not np.isfinite(inverse).all():
            raise CprError("Volume affine cannot be inverted to finite coordinates")
        return inverse, float(singular[-1])
    except (np.linalg.LinAlgError, ValueError, TypeError, FloatingPointError, OverflowError) as error:
        if isinstance(error, CprError):
            raise
        raise CprError("Invalid volume spatial geometry") from error


def _check_budget(rows: int, columns: int, slab_count: int):
    if rows * columns > MAX_OUTPUT_PIXELS:
        raise CprError(f"Image exceeds the {MAX_OUTPUT_PIXELS} pixel limit")
    if slab_count > MAX_SLAB_SAMPLES:
        raise CprError(f"Slab exceeds the {MAX_SLAB_SAMPLES} sample limit")
    if rows * columns * slab_count > MAX_SAMPLE_WORK:
        raise CprError(f"Request exceeds the {MAX_SAMPLE_WORK} voxel sample work limit")


class CprReslicer:
    def __init__(self, block_points: int = 16384):
        if isinstance(block_points, bool) or not isinstance(block_points, Integral) or not 1 <= block_points <= 16384:
            raise CprError("Block size must be an integer between 1 and 16384 points")
        self._block_points = int(block_points)

    def reslice(self, volume: DicomVolume, path: CprPath, settings: CprSettings) -> CprResult:
        check_render_cancelled()
        transform, source_step = _volume_transform(volume)
        line = sample_centerline(path, settings)
        offsets = _centered_offsets(settings.width_mm, settings.step_mm)
        slab_count = 1
        if settings.projection != "thin" and settings.thickness_mm > 0:
            slab_step = min(settings.step_mm, source_step)
            # Check the budget before division: corrupt subnormal spacing must
            # raise an input error, not overflow while computing a sample count.
            if settings.thickness_mm > (MAX_SLAB_SAMPLES - 1) * slab_step:
                raise CprError(f"Slab exceeds the {MAX_SLAB_SAMPLES} sample limit")
            slab_count = 2 * int(np.ceil(settings.thickness_mm / (2 * slab_step))) + 1
        rows, columns = len(offsets), len(line.distances_mm)
        _check_budget(rows, columns, slab_count)
        slabs = np.linspace(-settings.thickness_mm / 2, settings.thickness_mm / 2, slab_count) if slab_count > 1 else np.array([0.])
        output = np.empty(rows * columns, dtype=np.float32)
        for start in range(0, output.size, self._block_points):
            check_render_cancelled()
            stop = min(output.size, start + self._block_points)
            row, column = np.divmod(np.arange(start, stop), columns)
            points = line.points_patient[column] + offsets[row, None] * line.laterals_patient[column]
            output[start:stop] = self._sample_slab(
                volume, transform, points, line.binormals_patient[column], slabs, settings.projection)
        check_render_cancelled()
        return CprResult(readonly_array(output.reshape(rows, columns)), line,
                         readonly_array(offsets), settings, volume.series_uid, volume.fingerprint)

    def _sample_slab(self, volume, transform, points, normals, offsets, mode):
        count = np.zeros(len(points), dtype=np.int32)
        aggregate = np.full(len(points), -np.inf, dtype=np.float64) if mode == "mip" else np.zeros(len(points))
        for offset in offsets:
            check_render_cancelled()
            coordinates = (points + offset * normals) @ transform[:3, :3].T + transform[:3, 3]
            sampled = sample_volume(volume.modality_pixels, *coordinates.T)
            valid = np.isfinite(sampled)
            count += valid
            if mode == "mip":
                aggregate[valid] = np.maximum(aggregate[valid], sampled[valid])
            else:
                aggregate[valid] += sampled[valid]
        if mode == "mean":
            np.divide(aggregate, count, out=aggregate, where=count > 0)
        aggregate[count == 0] = np.nan
        return aggregate.astype(np.float32)

    def cross_section(self, volume: DicomVolume, centerline: CprCenterline, index: int,
                      *, width_mm: float, step_mm: float) -> CprCrossSection:
        check_render_cancelled()
        transform, _ = _volume_transform(volume)
        settings = CprSettings(width_mm=width_mm, step_mm=step_mm)
        if (isinstance(index, bool) or not isinstance(index, Integral)
                or not 0 <= index < len(centerline.distances_mm)):
            raise CprError("Cross-section index is outside the sampled path")
        offsets = _centered_offsets(settings.width_mm, settings.step_mm)
        size = len(offsets)
        _check_budget(size, size, 1)
        center = centerline.points_patient[index]
        u, b, tangent = (basis[index] for basis in (centerline.laterals_patient,
                          centerline.binormals_patient, centerline.tangents_patient))
        spacing = float(offsets[1] - offsets[0])
        geometry = MprImageGeometry(
            rows=size, columns=size, row_spacing=spacing, column_spacing=spacing,
            navigation_spacing=centerline.spacing_mm,
            frame=MprFrame.standard_lps(tuple(center)),
            image_origin_mpr=tuple(offsets[0] * (u + b)),
            row_direction_mpr=tuple(b), column_direction_mpr=tuple(u),
            navigation_direction_mpr=tuple(tangent),
        )
        output = np.empty(size * size, dtype=np.float32)
        for start in range(0, output.size, self._block_points):
            check_render_cancelled()
            stop = min(output.size, start + self._block_points)
            row, column = np.divmod(np.arange(start, stop), size)
            points = center + offsets[row, None] * b + offsets[column, None] * u
            coordinates = points @ transform[:3, :3].T + transform[:3, 3]
            output[start:stop] = sample_volume(volume.modality_pixels, *coordinates.T)
        check_render_cancelled()
        return CprCrossSection(
            readonly_array(output.reshape(size, size)), geometry, centerline.path_id,
            centerline.path_revision, centerline.algorithm_version,
            float(centerline.distances_mm[index]), volume.series_uid, volume.fingerprint,
        )
