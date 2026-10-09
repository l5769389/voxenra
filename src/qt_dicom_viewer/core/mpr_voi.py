"""Physical box/ellipsoid regions and native-voxel quantitative statistics."""
from qt_dicom_viewer.i18n import message as _msg
from dataclasses import dataclass
from itertools import product

import numpy as np


@dataclass(frozen=True)
class VoiRegion:
    center: tuple[float, float, float]
    # Unit axes: drawn columns, drawn rows, slice normal, in patient LPS.
    axes: tuple[tuple[float, float, float], ...]
    size: tuple[float, float, float]
    shape: str = "box"

    def __post_init__(self):
        if (self.shape not in ("box", "ellipsoid")
                or not np.isfinite([*self.center, *self.size]).all()
                or min(self.size) <= 0
                or not np.allclose(np.asarray(self.axes) @ np.asarray(self.axes).T,
                                   np.eye(3), atol=1e-6)):
            raise ValueError(_msg('text.0192'))

    @property
    def corners(self):
        return (np.asarray(list(product((-1, 1), repeat=3)))
                * np.asarray(self.size) / 2) @ np.asarray(self.axes) + self.center

    def contains(self, local):
        half = np.asarray(self.size)[:, None, None] / 2
        if self.shape == "ellipsoid":
            return np.sum((local / half) ** 2, axis=0) <= 1 + 1e-9
        return np.all((local >= -half - 1e-6) & (local < half - 1e-6), axis=0)


def automatic_depth(region, normal_spacing):
    if region.shape == "ellipsoid":
        return region.size[0]
    return max(normal_spacing, float(np.sqrt(region.size[0] * region.size[1])))


def box_from_drag(geometry, start, end, depth):
    u, v = np.asarray(geometry.column_direction_patient), np.asarray(geometry.row_direction_patient)
    midpoint = (np.asarray(start) + end) / 2
    center = (np.asarray(geometry.image_origin_patient)
              + u * midpoint[0] * geometry.column_spacing
              + v * midpoint[1] * geometry.row_spacing)
    size = (abs(end[0] - start[0]) * geometry.column_spacing,
            abs(end[1] - start[1]) * geometry.row_spacing, depth)
    return VoiRegion(tuple(center), tuple(map(tuple, (u, v, np.cross(u, v)))), size)


def circle_from_drag(geometry, center, edge, depth=None):
    """Center-to-edge drawing in physical millimeters, including unequal spacing."""
    u, v = np.asarray(geometry.column_direction_patient), np.asarray(geometry.row_direction_patient)
    position = (np.asarray(geometry.image_origin_patient) + u * center[0] * geometry.column_spacing
                + v * center[1] * geometry.row_spacing)
    delta = (np.asarray(edge) - center) * [geometry.column_spacing, geometry.row_spacing]
    diameter = 2 * float(np.linalg.norm(delta))
    return VoiRegion(tuple(position), tuple(map(tuple, (u, v, np.cross(u, v)))),
                     (diameter, diameter, diameter if depth is None else depth), "ellipsoid")


@dataclass
class VoiEvaluation:
    mask: np.ndarray  # Cropped native (slice, row, column), no full-volume copy.
    offset: np.ndarray
    geometry: object
    metrics: dict
    threshold: float | None
    value_range: tuple[float, float]


def evaluate_voi(volume, box, *, threshold=None, percent=False, pet=False):
    """Select voxel centers in a box/ellipsoid; padding/NaN never contributes.

    Boxes are half-open; ellipsoids include centers on their quadratic boundary.
    Percent means percent of VOI maximum for PET, or of min..max for CT.
    Scan in planes to bound temporary memory even for a large oblique box.
    """
    pixels, geometry = volume.modality_pixels, volume.geometry
    inverse = geometry.patient_to_voxel
    corners = box.corners @ inverse[:3, :3].T + inverse[:3, 3]
    lo = np.maximum(0, np.ceil(corners.min(axis=0) - 1e-6).astype(int))
    hi = np.minimum(pixels.shape, np.floor(corners.max(axis=0) + 1e-6).astype(int) + 1)
    hi = np.maximum(lo, hi)
    shape = tuple(hi - lo)
    mask = np.zeros(shape, dtype=bool)
    forward = geometry.voxel_to_patient
    axes = np.asarray(box.axes)
    matrix = axes @ forward[:3, :3]
    origin = axes @ (forward[:3, 3] - box.center)
    row = np.arange(lo[1], hi[1])[None, :, None]
    col = np.arange(lo[2], hi[2])[None, None, :]
    base = origin[:, None, None] + matrix[:, 1, None, None] * row + matrix[:, 2, None, None] * col
    cropped = pixels[tuple(slice(a, b) for a, b in zip(lo, hi))]
    count_total, minimum, maximum = 0, float("inf"), float("-inf")
    for local, index in enumerate(range(lo[0], hi[0])):
        p = base + matrix[:, 0, None, None] * index
        mask[local] = (box.contains(p)
                       & np.isfinite(pixels[index, lo[1]:hi[1], lo[2]:hi[2]]))
        values = cropped[local][mask[local]]
        count_total += values.size
        if values.size:
            minimum, maximum = min(minimum, float(values.min())), max(maximum, float(values.max()))
    if not count_total:
        minimum, maximum = 0., 0.
    effective = threshold
    if threshold is not None and percent:
        effective = maximum * threshold / 100 if pet else minimum + (maximum - minimum) * threshold / 100
    count, mean, m2 = 0, 0., 0.
    selected_min, selected_max = float("inf"), float("-inf")
    for local in range(shape[0]):
        if effective is not None:
            mask[local] &= cropped[local] >= effective
        values = cropped[local][mask[local]].astype(np.float64)
        n = int(values.size)
        if not n:
            continue
        block_mean = float(values.mean())
        residual = values - block_mean
        delta = block_mean - mean
        m2 += float(residual @ residual) + delta * delta * count * n / (count + n)
        mean += delta * n / (count + n)
        count += n
        selected_min = min(selected_min, float(values.min()))
        selected_max = max(selected_max, float(values.max()))
    voxel_mm3 = abs(float(np.linalg.det(forward[:3, :3])))
    metrics = dict(count=count, volume=count * voxel_mm3 / 1000,
                   mean=mean if count else None,
                   minimum=selected_min if count else None,
                   maximum=selected_max if count else None,
                   sd=float(np.sqrt(m2 / count)) if count else None,
                   fraction=count / count_total * 100 if count_total else 0.)
    return VoiEvaluation(mask, lo, geometry, metrics, effective, (minimum, maximum))


def plane_polygon(box, geometry):
    """Intersect the physical region with an arbitrary/oblique MPR plane."""
    if box.shape == "ellipsoid":
        return _ellipsoid_section(box, geometry)
    corners = box.corners
    normal = np.cross(geometry.column_direction_patient, geometry.row_direction_patient)
    distances = (corners - geometry.image_origin_patient) @ normal
    points = []
    for i in range(8):
        for bit in (1, 2, 4):
            j = i ^ bit
            if j < i:
                continue
            a, b = distances[i], distances[j]
            if abs(a) < 1e-6:
                points.append(corners[i])
            if abs(b) < 1e-6:
                points.append(corners[j])
            if a * b < 0:
                points.append(corners[i] + (corners[j] - corners[i]) * a / (a - b))
    if len(points) < 3:
        return []
    local = (np.asarray(points) - geometry.image_origin_patient)
    coords = np.column_stack((local @ geometry.column_direction_patient / geometry.column_spacing,
                              local @ geometry.row_direction_patient / geometry.row_spacing))
    coords = np.unique(np.round(coords, 7), axis=0)
    center = coords.mean(axis=0)
    order = np.argsort(np.arctan2(coords[:, 1] - center[1], coords[:, 0] - center[0]))
    return coords[order].tolist()


def _ellipsoid_section(region, geometry):
    # Restrict the ellipsoid quadratic form to the displayed plane, then solve
    # its ellipse. A projected bounding circle would be wrong away from center.
    normalized_axes = np.asarray(region.axes) / (np.asarray(region.size)[:, None] / 2)
    basis = normalized_axes @ np.column_stack((geometry.column_direction_patient,
                                               geometry.row_direction_patient))
    offset = normalized_axes @ (np.asarray(geometry.image_origin_patient) - region.center)
    quadratic = basis.T @ basis
    linear = basis.T @ offset
    center = -np.linalg.solve(quadratic, linear)
    extent = 1 - float(offset @ offset + linear @ center)
    if extent <= 1e-10:
        return []
    eigenvalues, directions = np.linalg.eigh(quadratic)
    angles = np.arange(128) * (2 * np.pi / 128)
    circle = np.column_stack((np.cos(angles), np.sin(angles)))
    points = (circle * np.sqrt(extent / eigenvalues)) @ directions.T + center
    return (points / [geometry.column_spacing, geometry.row_spacing]).tolist()


def editing_handles(region, geometry):
    """Only the original central drawing plane exposes resize handles."""
    if (not np.allclose(region.axes[:2], [geometry.column_direction_patient, geometry.row_direction_patient])
            or abs(np.dot(np.asarray(region.center) - geometry.image_origin_patient, region.axes[2])) >= 1e-4):
        return []
    if region.shape == "box":
        return plane_polygon(region, geometry)
    local = np.asarray(region.center) - geometry.image_origin_patient
    center = np.array([local @ region.axes[0], local @ region.axes[1]])
    cardinal = np.array([[1, 0], [0, 1], [-1, 0], [0, -1]]) * np.asarray(region.size[:2]) / 2
    return ((cardinal + center) / [geometry.column_spacing, geometry.row_spacing]).tolist()


def plane_mask(evaluation, geometry):
    """Nearest native mask voxel, with bounded coordinate temporaries.

    Row blocks retain the same arithmetic and half-voxel boundary rule as the
    full grid. A large output plane need not allocate several full 3D index
    arrays merely to display a binary overlay.
    """
    inverse = evaluation.geometry.patient_to_voxel
    origin = inverse[:3, :3] @ geometry.image_origin_patient + inverse[:3, 3]
    u = inverse[:3, :3] @ np.asarray(geometry.column_direction_patient) * geometry.column_spacing
    v = inverse[:3, :3] @ np.asarray(geometry.row_direction_patient) * geometry.row_spacing
    cols = np.arange(geometry.columns, dtype=np.float32)[None, :]
    base = origin[:, None, None] + u[:, None, None] * cols
    shape = np.asarray(evaluation.mask.shape)[:, None, None]
    offset = evaluation.offset[:, None, None]
    result = np.zeros((geometry.rows, geometry.columns), dtype=bool)
    block_rows = max(1, 65536 // max(1, geometry.columns))
    for first in range(0, geometry.rows, block_rows):
        stop = min(first + block_rows, geometry.rows)
        rows = np.arange(first, stop, dtype=np.float32)[:, None]
        index = np.floor(base + v[:, None, None] * rows + .5).astype(int) - offset
        inside = np.all((index >= 0) & (index < shape), axis=0)
        block = result[first:stop]
        block[inside] = evaluation.mask[tuple(index[:, inside])]
    return result
