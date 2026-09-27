"""Persistent binary masks on the original DICOM grid, independent of thresholds."""

from uuid import uuid4

import numpy as np

from qt_dicom_viewer.core.mpr_voi import VoiEvaluation, VoiRegion
from qt_dicom_viewer.core.freehand_roi import simple_polygon, polygon_mask, roi_outline
from qt_dicom_viewer.core.workspace_state import MAX_MASK_VOXELS
from qt_dicom_viewer.i18n import message as _msg


def evaluate_mask(volume, record):
    mask = record["mask"]
    offset = np.asarray(record["mask_offset"], dtype=int)
    affine = np.asarray(record["mask_affine"], dtype=float)
    if (
        mask.dtype != bool
        or mask.ndim != 3
        or offset.shape != (3,)
        or min(mask.shape) <= 0
        or mask.size > MAX_MASK_VOXELS
        or np.any(offset < 0)
        or np.any(offset + mask.shape > volume.modality_pixels.shape)
        or affine.shape != (4, 4)
        or not np.allclose(affine, volume.geometry.voxel_to_patient, atol=1e-5, rtol=0)
    ):
        raise ValueError(_msg("results.geometryMismatch"))
    pixels = volume.modality_pixels[
        tuple(slice(int(a), int(a + b)) for a, b in zip(offset, mask.shape))
    ]
    count = int(mask.sum())
    values = pixels[mask & np.isfinite(pixels)].astype(np.float64)
    minimum, maximum = (
        (float(values.min()), float(values.max())) if values.size else (0.0, 0.0)
    )
    metrics = dict(
        count=count,
        volume=count * abs(float(np.linalg.det(affine[:3, :3]))) / 1000,
        mean=float(values.mean()) if values.size else None,
        sd=float(values.std()) if values.size else None,
        minimum=minimum if values.size else None,
        maximum=maximum if values.size else None,
        fraction=100.0,
    )
    return VoiEvaluation(
        mask, offset, volume.geometry, metrics, None, (minimum, maximum)
    )


def mask_record(volume, mask, offset, *, name, color="#ed55ed", phase=None, allow_empty=False, **metadata):
    """Crop and own the mask; all stored fields round-trip through workspace JSON."""
    if mask.dtype != bool or mask.ndim != 3 or (not mask.any() and not allow_empty):
        raise ValueError(_msg("results.emptySegment", name=name))
    active = [
        np.flatnonzero(mask.any(axis=tuple(j for j in range(3) if j != i)))
        for i in range(3)
    ]
    lo, hi = ((np.array([a[0] for a in active]), np.array([a[-1] + 1 for a in active]))
              if mask.any() else (np.zeros(3, int), np.ones(3, int)))
    cropped = mask[tuple(slice(a, b) for a, b in zip(lo, hi))].copy()
    origin = np.asarray(offset, dtype=int) + lo
    g = volume.geometry
    center = (g.voxel_to_patient @ [*(origin + (np.array(cropped.shape) - 1) / 2), 1])[
        :3
    ]
    size = np.array(cropped.shape)[::-1] * [
        g.column_spacing,
        g.row_spacing,
        g.slice_spacing,
    ]
    region = VoiRegion(
        tuple(map(float, center)),
        tuple(
            map(
                tuple,
                (
                    g.column_index_direction_patient,
                    g.row_index_direction_patient,
                    g.slice_index_direction_patient,
                ),
            )
        ),
        tuple(map(float, size)),
    )
    meta = volume.pixel_value_meta
    record = dict(
        id=str(uuid4()),
        kind="segmentation",
        series=volume.series_uid,
        phase=phase,
        name=str(name)[:120],
        color=color,
        visible=True,
        region=region,
        mask=cropped,
        mask_offset=tuple(map(int, origin)),
        mask_affine=g.voxel_to_patient,
        threshold=0.0,
        percent=False,
        pet=meta.is_suv,
        unit=meta.unit_id,
        unitLabel=meta.unit or "Source",
        unitOptions=[
            dict(id=o.unit_id, label=o.unit) for o in meta.unit_options if o.available
        ],
        depthAuto=False,
        depthMax=float(max(size)),
        normalSpacing=g.slice_spacing,
        **metadata,
    )
    return record, evaluate_mask(volume, record)


def roi_to_mask(volume, measurement, frame, *, phase=None):
    """Rasterize a closed freehand ROI on the nearest parallel native voxel layer.

    The source grid is sampled at voxel centers. No extrusion, interpolation or
    threshold is implied by converting one planar measurement.
    """
    outline = roi_outline(measurement.points, getattr(measurement, "smooth", False))
    if (
        str(getattr(measurement, "kind", "")) != "freehand"
        or not simple_polygon(outline)
        or frame is None
        or len(frame) != 6
        or len(frame[5]) != 11
        or measurement.series_uid != volume.series_uid
    ):
        raise ValueError(_msg("seg.roiRequired"))
    pose = np.asarray(frame[5], dtype=float)
    if not np.isfinite(pose).all() or min(pose[:2]) <= 0:
        raise ValueError(_msg("seg.roiPlane"))
    u, v = pose[5:8], pose[8:11]
    if not np.allclose(np.array([u, v]) @ np.array([u, v]).T, np.eye(2), atol=1e-5):
        raise ValueError(_msg("seg.roiPlane"))
    g = volume.geometry
    inverse = g.patient_to_voxel
    axes = np.column_stack((u * pose[1], v * pose[0]))
    native_axes = inverse[:3, :3] @ axes
    # Parallel planes may use a different display sampling step, but must align
    # to two different original voxel axes. Oblique contours need a slab policy.
    indices = np.argmax(abs(native_axes), axis=0)
    if indices[0] == indices[1] or any(
        np.max(abs(np.delete(native_axes[:, j], indices[j]))) > 1e-5 for j in (0, 1)
    ):
        raise ValueError(_msg("seg.roiPlane"))
    normal = next(i for i in range(3) if i not in indices)
    anchor = (inverse @ [*pose[2:5], 1])[:3]
    k = int(np.floor(anchor[normal] + 0.5))
    if not 0 <= k < volume.modality_pixels.shape[normal]:
        raise ValueError(_msg("seg.roiPlane"))
    # Express the polygon in the two native in-plane index axes, then use the
    # same boundary-inclusive center rule as ordinary freehand statistics.
    from qt_dicom_viewer.model import ImagePoint

    native = (
        np.array([(p.column, p.row) for p in outline]) @ native_axes.T
        + anchor
    )
    xaxis, yaxis = map(int, indices)
    lo = np.maximum(0, np.floor(native.min(axis=0)).astype(int))
    hi = np.minimum(
        volume.modality_pixels.shape, np.ceil(native.max(axis=0)).astype(int) + 1
    )
    lo[normal], hi[normal] = k, k + 1
    if np.any(hi <= lo):
        raise ValueError(
            _msg("results.emptySegment", name=_msg("measurement.freehand"))
        )
    if int(np.prod(hi - lo)) > MAX_MASK_VOXELS:
        raise ValueError(_msg("seg.tooLarge"))
    polygon = [ImagePoint(float(p[xaxis]), float(p[yaxis])) for p in native]
    plane = polygon_mask(polygon, lo[xaxis], hi[xaxis] - 1, lo[yaxis], hi[yaxis] - 1)
    mask = np.zeros(tuple(hi - lo), dtype=bool)
    yy, xx = np.nonzero(plane)
    selected = np.zeros((3, len(xx)), dtype=int)
    selected[xaxis], selected[yaxis] = xx, yy
    mask[tuple(selected)] = True
    return mask_record(
        volume,
        mask,
        lo,
        name=str(_msg("seg.roiName")),
        phase=phase,
        mask_origin="roi",
        source_measurement_id=measurement.measurement_id,
    )
