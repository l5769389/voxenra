"""Non-destructive 3D selection and table suppression masks."""
from voxplane.i18n import message as _msg
import numpy as np

from .volume_view import camera_parameters, view_basis


def simplify_polygon(points, tolerance=1.0):
    """Reduce freehand samples without changing the outline by more than a pixel."""
    points = np.asarray(points, dtype=float)
    if len(points) <= 2:
        return points
    keep, pending = {0, len(points)-1}, [(0, len(points)-1)]
    while pending:
        start, end = pending.pop()
        if end-start < 2:
            continue
        delta = points[end] - points[start]
        length2 = delta @ delta
        section = points[start:end+1]
        t = np.clip((section-points[start]) @ delta / max(length2, 1e-12), 0, 1)
        distances = np.linalg.norm(section-(points[start]+t[:, None]*delta), axis=1)
        offset = int(np.argmax(distances))
        if distances[offset] > tolerance:
            middle = start+offset
            keep.add(middle)
            pending.extend(((start, middle), (middle, end)))
    return points[sorted(keep)]


def polygon_area(points):
    p = np.asarray(points, dtype=float)
    if len(p) < 3 or not np.all(np.isfinite(p)):
        return 0.0
    return abs(float(np.sum(p[:, 0]*np.roll(p[:, 1], -1)
                            - p[:, 1]*np.roll(p[:, 0], -1)))) / 2


def polygon_contains(x, y, polygon):
    """Even/odd fill, including the boundary, for concave screen-space polygons."""
    inside = np.zeros(x.shape, dtype=bool)
    boundary = inside.copy()
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        dx, dy = b-a
        cross = (x-a[0])*dy - (y-a[1])*dx
        boundary |= ((np.abs(cross) < 1e-7) & (x >= min(a[0], b[0])-1e-7)
                     & (x <= max(a[0], b[0])+1e-7) & (y >= min(a[1], b[1])-1e-7)
                     & (y <= max(a[1], b[1])+1e-7))
        if abs(dy) > 1e-12:
            inside ^= ((a[1] > y) != (b[1] > y)) & (x < a[0]+(y-a[1])*dx/dy)
    return inside | boundary


def crop_keep_mask(geometry, state, size, points, mode, previous=None):
    """Extrude a screen selection through the volume along the frozen camera ray.

    Coordinates are logical Qt pixels, matching camera_parameters (including
    pan/zoom and portrait aspect ratios). Evaluate a slice at a time so there
    is no full-volume float coordinate grid. True means visible.
    """
    polygon = np.asarray(points, dtype=float)
    if mode not in ("inside", "outside") or polygon_area(polygon) < 9:
        raise ValueError(_msg('text.0129'))
    if min(size) <= 0:
        raise ValueError(_msg('text.0130'))
    p = camera_parameters(geometry, state, size)
    basis = view_basis(state)
    projection = np.stack((basis[:, 0], -basis[:, 1])) * size[1]/(2*p["scale"])
    affine = projection @ geometry.voxel_to_patient[:3]
    affine[:, 3] += np.asarray(size)/2 - projection @ p["focal"]
    rows, cols = np.ogrid[:geometry.rows, :geometry.columns]
    base_x = affine[0, 1]*rows + affine[0, 2]*cols + affine[0, 3]
    base_y = affine[1, 1]*rows + affine[1, 2]*cols + affine[1, 3]
    result = np.empty((geometry.slice_count, geometry.rows, geometry.columns), dtype=bool)
    low, high = polygon.min(axis=0), polygon.max(axis=0)
    for k in range(geometry.slice_count):
        x, y = base_x + affine[0, 0]*k, base_y + affine[1, 0]*k
        candidate = (x >= low[0]) & (x <= high[0]) & (y >= low[1]) & (y <= high[1])
        selected = np.zeros(candidate.shape, dtype=bool)
        selected[candidate] = polygon_contains(x[candidate], y[candidate], polygon)
        result[k] = ~selected if mode == "inside" else selected
        if previous is not None:
            result[k] &= previous[k]
    return result


def _labels(mask):
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    from vtkmodules.vtkCommonDataModel import vtkImageData
    from vtkmodules.vtkImagingMorphological import vtkImageConnectivityFilter

    pixels = np.ascontiguousarray(mask, dtype=np.uint8)
    image = vtkImageData()
    image.SetDimensions(mask.shape[1], mask.shape[0], 1)
    image.GetPointData().SetScalars(numpy_to_vtk(pixels.ravel(), deep=False))
    regions = vtkImageConnectivityFilter()
    regions.SetInputData(image)
    regions.SetScalarRange(1, 1)
    regions.SetLabelScalarTypeToInt()
    regions.SetExtractionModeToAllRegions()
    regions.Update()
    return vtk_to_numpy(regions.GetOutput().GetPointData().GetScalars()).reshape(mask.shape).copy()


def _box_filter(mask, radii, dilate):
    result = mask
    for axis, radius in enumerate(radii):
        if not radius:
            continue
        pad = [(0, 0)] * 2
        pad[axis] = (radius+1, radius)
        sums = np.cumsum(np.pad(result, pad), axis=axis, dtype=np.int32)
        lo, hi = [slice(None)]*2, [slice(None)]*2
        lo[axis], hi[axis] = slice(None, -2*radius-1), slice(2*radius+1, None)
        count = sums[tuple(hi)] - sums[tuple(lo)]
        result = count > 0 if dilate else count == 2*radius+1
    return result


def _fill_holes(mask):
    labels = _labels(~mask)
    exterior = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    return mask | ~np.isin(labels, exterior)


def bed_keep_mask(volume):
    """CT body envelope: remove thin supports, retain substantial body components.

    Work in the acquisition plane nearest patient transverse (including axis
    permutations and reversed axes). A 5 mm opening separates thin table/body
    contacts; component shape rejects broad flat supports. Fill enclosed air
    spaces so lung/airway voxels remain available to every transfer function.
    This is a display heuristic, not anatomical segmentation.
    """
    g = volume.geometry
    directions = (g.slice_index_direction_patient, g.row_index_direction_patient,
                  g.column_index_direction_patient)
    axis = int(np.argmax(np.abs(np.asarray(directions)[:, 2])))
    spacings = np.array((g.slice_spacing, g.row_spacing, g.column_spacing))
    in_plane = np.delete(spacings, axis)
    radii = tuple(max(1, int(np.ceil(5/s))) for s in in_plane)
    planes = np.moveaxis(volume.modality_pixels, axis, 0)
    masks = np.ones(planes.shape, dtype=bool)
    found = []
    for index, plane in enumerate(planes):
        tissue = plane > -500
        # Fill lungs before erosion, otherwise a thin thoracic wall may vanish.
        envelope = _fill_holes(tissue)
        labels = _labels(_box_filter(envelope, radii, False))
        components = []
        for label in np.unique(labels):
            if label == 0:
                continue
            coords = np.nonzero(labels == label)
            extent = np.array([np.ptp(c)+1 for c in coords]) * in_plane
            area = len(coords[0])*np.prod(in_plane)
            if area >= 40 and min(extent) >= 6 and max(extent)/min(extent) <= 8:
                components.append((int(label), area))
        if not components:
            continue
        largest = max(area for _, area in components)
        keep = np.isin(labels, [label for label, area in components if area >= largest*0.01])
        masks[index] = _fill_holes(_box_filter(keep, radii, True))
        found.append(index)
    if not found:
        raise ValueError(_msg('text.0131'))
    # At the ends of a scan the body can be too small to survive opening.
    # Use the nearest valid envelope to avoid restoring the table on those slices.
    for index in set(range(len(planes))) - set(found):
        nearest = min(found, key=lambda other: abs(other-index))
        masks[index] = masks[nearest]
    return np.ascontiguousarray(np.moveaxis(masks, 0, axis))
