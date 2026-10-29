"""Arc-length sampling and minimal-rotation frames for a directed 3D polyline.

Frames are transported through *source segments*, not output samples: changing
the display resolution must never change the orientation at a physical point.
At a corner the outgoing segment defines the one-sided tangent.
"""
from __future__ import annotations

import numpy as np

from qt_dicom_viewer.core.render_cancellation import check_render_cancelled
from qt_dicom_viewer.model.cpr import (
    CprCenterline, CprError, CprPath, CprSettings, MAX_AXIS_SAMPLES, readonly_array,
)


def sample_centerline(path: CprPath, settings: CprSettings) -> CprCenterline:
    check_render_cancelled()
    points = np.asarray(path.control_points, dtype=np.float64)
    vectors = np.diff(points, axis=0)
    lengths = np.linalg.norm(vectors, axis=1)
    cumulative = np.concatenate(([0.], np.cumsum(lengths)))
    intervals = int(np.ceil(cumulative[-1] / settings.step_mm))
    if intervals + 1 > MAX_AXIS_SAMPLES:
        raise CprError(f"Centerline exceeds the {MAX_AXIS_SAMPLES} sample limit")
    directions = vectors / lengths[:, None]
    laterals = np.empty_like(directions)
    first = directions[0]
    up = np.asarray(settings.up_patient)
    projected = up - first * np.dot(first, up)
    if np.linalg.norm(projected) < 1e-6:
        up = np.eye(3)[np.argmin(np.abs(first))]
        projected = up - first * np.dot(first, up)
    laterals[0] = projected / np.linalg.norm(projected)
    for index in range(1, len(directions)):
        check_render_cancelled()
        before, after = directions[index - 1:index + 1]
        cosine = float(np.clip(np.dot(before, after), -1, 1))
        axis = np.cross(before, after)
        previous = laterals[index - 1]
        # Rodrigues' shortest rotation, expressed without an angle division.
        transported = (previous + np.cross(axis, previous)
                       + np.cross(axis, np.cross(axis, previous)) / (1 + cosine))
        transported -= after * np.dot(transported, after)
        laterals[index] = transported / np.linalg.norm(transported)
    check_render_cancelled()
    distances = np.linspace(0., cumulative[-1], intervals + 1)
    segments = np.minimum(np.searchsorted(cumulative, distances, side="right") - 1, len(lengths) - 1)
    positions = points[segments] + (distances - cumulative[segments])[:, None] * directions[segments]
    positions[0], positions[-1] = points[0], points[-1]
    tangents = directions[segments]
    u = laterals[segments]
    b = np.cross(tangents, u)
    rotated = np.cos(settings.angle_radians) * u + np.sin(settings.angle_radians) * b
    return CprCenterline(
        path.path_id, path.revision, path.algorithm_version,
        readonly_array(distances), readonly_array(positions), readonly_array(tangents),
        readonly_array(rotated), readonly_array(np.cross(tangents, rotated)),
    )
