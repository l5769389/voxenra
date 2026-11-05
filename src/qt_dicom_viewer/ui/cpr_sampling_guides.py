"""Project the displayed CPR sampling line into a reference image.

This is display geometry only. It never changes the reslicing frame or path.
"""
from __future__ import annotations

import numpy as np

from qt_dicom_viewer.model.dicom_core import MprImageGeometry


def project_sampling_line(reference: MprImageGeometry, center_patient,
                          direction_patient, width_mm: float) -> dict:
    center = np.asarray(center_patient, dtype=float)
    half_line = np.asarray(direction_patient, dtype=float) * (width_mm / 2)
    points = np.array([center - half_line, center, center + half_line])
    transform = reference.patient_to_image_index
    start, middle, end = points @ transform[:3, :3].T + transform[:3, 3]
    # Reference images are discrete slices. A center within half a navigation
    # sample belongs to the displayed slice, as for the existing station marker.
    on_plane = bool(abs(middle[0]) <= .5 + 1e-8)
    physical_span = (end - start) * np.array([
        reference.navigation_spacing, reference.row_spacing, reference.column_spacing])
    collapsed = np.linalg.norm(physical_span[1:]) <= 1e-6
    in_plane = abs(physical_span[0]) <= 1e-6
    return dict(startColumn=float(start[2]), startRow=float(start[1]),
                endColumn=float(end[2]), endRow=float(end[1]),
                centerColumn=float(middle[2]), centerRow=float(middle[1]),
                centerOnPlane=on_plane,
                endOn=bool(collapsed),
                projected=not (on_plane and (in_plane or collapsed)))
