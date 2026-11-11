"""Named MPR layouts and patient-space reference geometry (no UI dependency)."""
from itertools import product
from voxplane.i18n import message as _msg

import numpy as np


# row, column, row span, column span; preserve the original default placement.
MPR_LAYOUTS = {
    "right": (_msg("mpr.layout.right"), 2, 2, ((0, 0, 1, 1), (0, 1, 2, 1), (1, 0, 1, 1))),
    "left": (_msg("mpr.layout.left"), 2, 2, ((0, 0, 2, 1), (0, 1, 1, 1), (1, 1, 1, 1))),
    "columns": (_msg("mpr.layout.columns"), 1, 3, ((0, 0, 1, 1), (0, 1, 1, 1), (0, 2, 1, 1))),
    "rows": (_msg("mpr.layout.rows"), 3, 1, ((0, 0, 1, 1), (1, 0, 1, 1), (2, 0, 1, 1))),
    "top": (_msg("mpr.layout.top"), 2, 2, ((0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1))),
    "bottom": (_msg("mpr.layout.bottom"), 2, 2, ((0, 0, 1, 1), (1, 0, 1, 2), (0, 1, 1, 1))),
    "quad": (_msg("mpr.layout.quad"), 2, 2, ((0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1))),
}


def layout_items():
    return [dict(value=key, label=value[0], icon="layout-" + key) for key, value in MPR_LAYOUTS.items()]


def placements(key):
    return {plane: dict(row=p[0], column=p[1], rowSpan=p[2], columnSpan=p[3])
            for plane, p in zip(("axial", "coronal", "sagittal"), MPR_LAYOUTS[key][3])}


def plane_box_intersection(geometry, center, normal):
    """Intersect a patient-space plane with the oriented voxel-center bounds."""
    origin = np.asarray(geometry.origin_patient)
    axes = np.column_stack((geometry.column_index_direction_patient,
                            geometry.row_index_direction_patient,
                            geometry.slice_index_direction_patient))
    extent = np.array(((geometry.columns - 1) * geometry.column_spacing,
                       (geometry.rows - 1) * geometry.row_spacing,
                       (geometry.slice_count - 1) * geometry.slice_spacing))
    corners = np.array([origin + axes @ (np.array(c) * extent) for c in product((0, 1), repeat=3)])
    bits = list(product((0, 1), repeat=3))
    points = []
    center, normal = np.asarray(center), np.asarray(normal)
    for i, a in enumerate(bits):
        for j in range(i + 1, 8):
            if sum(x != y for x, y in zip(a, bits[j])) != 1:
                continue
            p, q = corners[i], corners[j]
            dp, dq = np.dot(p-center, normal), np.dot(q-center, normal)
            for point in ([p] if abs(dp) < 1e-7 else []) + ([q] if abs(dq) < 1e-7 else []):
                if not any(np.linalg.norm(point-r) < 1e-6 for r in points):
                    points.append(point)
            if dp * dq < 0:
                point = p + dp / (dp-dq) * (q-p)
                if not any(np.linalg.norm(point-r) < 1e-6 for r in points):
                    points.append(point)
    if len(points) < 3:
        return ()
    mid = np.mean(points, axis=0)
    u = points[0]-mid
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    points.sort(key=lambda p: np.arctan2(np.dot(p-mid, v), np.dot(p-mid, u)))
    return tuple(tuple(float(x) for x in p) for p in points)


def matrix_quaternion(matrix):
    """Stable quaternion conversion, including rotations near 180 degrees."""
    m = np.asarray(matrix)
    k = np.array((
        (m[0,0]-m[1,1]-m[2,2], m[0,1]+m[1,0], m[0,2]+m[2,0], m[2,1]-m[1,2]),
        (m[0,1]+m[1,0], m[1,1]-m[0,0]-m[2,2], m[1,2]+m[2,1], m[0,2]-m[2,0]),
        (m[0,2]+m[2,0], m[1,2]+m[2,1], m[2,2]-m[0,0]-m[1,1], m[1,0]-m[0,1]),
        (m[2,1]-m[1,2], m[0,2]-m[2,0], m[1,0]-m[0,1], np.trace(m)),
    )) / 3
    q = np.linalg.eigh(k)[1][:, -1][[3, 0, 1, 2]]
    return tuple(float(v) for v in (q if q[0] >= 0 else -q))
