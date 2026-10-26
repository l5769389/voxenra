"""Water phantom detection and five circular ROIs in original CT HU pixels.

All distances are physical millimetres. Image display transforms and windowing
never participate. The metrics are measurements, without acceptance thresholds.
"""
from qt_dicom_viewer.i18n import message as _msg
from dataclasses import replace
import math

import numpy as np

from qt_dicom_viewer.model.water_qa import WaterPhantom, WaterQaSettings, WaterQaRoi, WaterQaResult


class WaterPhantomDetectionError(ValueError):
    """No unique water boundary; valid images can still be sampled manually."""
    def __init__(self, message_key):
        self.message_key = message_key
        super().__init__(_msg(message_key))


def _validate_input(pixels, spacing):
    array = np.asarray(pixels)
    if array.ndim != 2 or min(array.shape) < 16:
        raise ValueError(_msg('text.0076'))
    if spacing is None or len(spacing) != 2:
        raise ValueError(_msg('text.0077'))
    spacing = tuple(float(s) for s in spacing)
    if not all(math.isfinite(s) and s > 0 for s in spacing):
        raise ValueError(_msg('text.0078'))
    if not np.all(np.isfinite(array)):
        raise ValueError(_msg('text.0079'))
    return array, spacing


def _components(mask):
    # QA is optional during a viewing session. Load its native filters only
    # when detection runs, rather than while constructing the empty workspace.
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    from vtkmodules.vtkCommonDataModel import vtkImageData
    from vtkmodules.vtkImagingMorphological import vtkImageConnectivityFilter

    data = np.ascontiguousarray(mask, dtype=np.uint8)
    image = vtkImageData()
    image.SetDimensions(data.shape[1], data.shape[0], 1)
    image.GetPointData().SetScalars(numpy_to_vtk(data.ravel(), deep=False))
    connectivity = vtkImageConnectivityFilter()
    connectivity.SetInputData(image)
    connectivity.SetScalarRange(1, 1)
    connectivity.SetLabelScalarTypeToInt()
    connectivity.SetExtractionModeToAllRegions()
    connectivity.Update()
    return vtk_to_numpy(connectivity.GetOutput().GetPointData().GetScalars()).reshape(data.shape).copy()


def _circle_fit(points):
    origin = np.mean(points, axis=0)
    local = points-origin
    matrix = np.column_stack((2*local, np.ones(len(local))))
    values, _, rank, _ = np.linalg.lstsq(matrix, np.sum(local*local, axis=1), rcond=None)
    radius2 = values[2]+values[:2]@values[:2]
    if rank < 3 or radius2 <= 0:
        return None
    return values[:2]+origin, math.sqrt(radius2)


def _round_boundary(mask, spacing):
    """Robust circle fit can ignore a narrow holder attached to the phantom."""
    interior = np.zeros_like(mask)
    interior[1:-1, 1:-1] = (mask[:-2, 1:-1] & mask[2:, 1:-1]
                             & mask[1:-1, :-2] & mask[1:-1, 2:])
    rows, columns = np.nonzero(mask & ~interior)
    if len(rows) < 40:
        return None
    points = np.column_stack((columns*spacing[1], rows*spacing[0]))
    if len(points) > 1600:
        points = points[np.linspace(0, len(points)-1, 1600, dtype=int)]
    tolerance = max(1.5, max(spacing)*1.5)
    minimum_radius = 20.0
    maximum_radius = min((mask.shape[1]-1)*spacing[1], (mask.shape[0]-1)*spacing[0])/2
    candidates = [_circle_fit(points)]
    rng = np.random.default_rng(731)
    candidates.extend(_circle_fit(points[rng.choice(len(points), 3, replace=False)]) for _ in range(160))
    best, best_score = None, -1
    for candidate in candidates:
        if candidate is None:
            continue
        center, radius = candidate
        if not minimum_radius <= radius <= maximum_radius:
            continue
        distances = np.linalg.norm(points-center, axis=1)
        inliers = np.abs(distances-radius) <= tolerance
        if np.count_nonzero(inliers) < 35:
            continue
        angles = np.arctan2(*(points[inliers]-center)[:, ::-1].T)
        coverage = len(np.unique(np.floor((angles+np.pi)*36/(2*np.pi)).astype(int) % 36))/36
        if coverage < 0.86:
            continue
        score = np.count_nonzero(inliers)*coverage
        if score > best_score:
            best, best_score = (center, radius, coverage, inliers), score
    if best is None:
        return None
    center, radius, coverage, inliers = best
    for _ in range(3):
        fit = _circle_fit(points[inliers])
        if fit is None:
            return None
        center, radius = fit
        inliers = np.abs(np.linalg.norm(points-center, axis=1)-radius) <= tolerance
    # Refuse clipped phantoms; inventing their missing edge biases peripheral ROIs.
    margin = max(spacing)
    if (center[0]-radius < margin or center[1]-radius < margin
            or center[0]+radius > (mask.shape[1]-1)*spacing[1]-margin
            or center[1]+radius > (mask.shape[0]-1)*spacing[0]-margin):
        return None
    return WaterPhantom(float(center[0]/spacing[1]), float(center[1]/spacing[0]), float(radius), float(coverage))


def detect_water_phantom(pixels, spacing):
    array, spacing = _validate_input(pixels, spacing)
    # This broad detection interval is NOT an acceptance criterion or a filter
    # on samples used for statistics. Every original voxel in each ROI is used.
    labels = _components((array > -300) & (array < 300))
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    candidates = []
    y, x = np.ogrid[:array.shape[0], :array.shape[1]]
    for label in np.argsort(counts)[-5:][::-1]:
        if counts[label]*spacing[0]*spacing[1] < math.pi*20**2:
            continue
        phantom = _round_boundary(labels == label, spacing)
        if phantom is None:
            continue
        disk = ((x-phantom.column)*spacing[1])**2 + ((y-phantom.row)*spacing[0])**2
        values = array[disk <= (phantom.radius_mm*0.7)**2]
        if len(values) < 64 or abs(float(np.median(values))) > 80:
            continue
        if np.mean(np.abs(values) < 150) < 0.9:
            continue
        candidates.append(phantom)
    if not candidates:
        raise WaterPhantomDetectionError('text.0080')
    candidates.sort(key=lambda p: p.radius_mm, reverse=True)
    if len(candidates) > 1 and candidates[1].radius_mm > candidates[0].radius_mm*0.85:
        raise WaterPhantomDetectionError('text.0081')
    return candidates[0]


def _measure_roi(array, spacing, phantom, key, label, column, row, radius):
    if (not all(math.isfinite(v) for v in (column, row, radius)) or radius <= 0
            or (phantom is not None and math.hypot((column-phantom.column)*spacing[1], (row-phantom.row)*spacing[0]) + radius > phantom.radius_mm + 1e-6)):
        raise ValueError(_msg('text.0090'))
    # QML QVariant maps need Python floats, not NumPy scalar wrappers.
    column, row = float(column), float(row)
    rx, ry = radius/spacing[1], radius/spacing[0]
    x0, x1 = math.ceil(column-rx), math.floor(column+rx)+1
    y0, y1 = math.ceil(row-ry), math.floor(row+ry)+1
    if x0 < 0 or y0 < 0 or x1 > array.shape[1] or y1 > array.shape[0]:
        raise ValueError(_msg('text.0092'))
    y, x = np.ogrid[y0:y1, x0:x1]
    inside = ((x-column)*spacing[1])**2 + ((y-row)*spacing[0])**2 <= radius**2
    values = array[y0:y1, x0:x1][inside].astype(np.float64)
    if len(values) < 16:
        raise ValueError(_msg('text.0093'))
    # Do not reject outlier HU samples or drop non-water pixels here: doing
    # so would hide image artefacts and underestimate noise/nonuniformity.
    return WaterQaRoi(key, label, column, row, radius, len(values),
                          len(values)*spacing[0]*spacing[1], float(values.mean()),
                          float(values.std(ddof=0)), float(values.min()), float(values.max()), 0)


def measure_water_phantom(pixels, spacing, phantom, settings=WaterQaSettings(), *, centers=None, extra_rois=()):
    """Sample five ROIs, optionally at manually adjusted (column, row) centers."""
    array, spacing = _validate_input(pixels, spacing)
    diameter, clearance = settings.roi_diameter_mm, settings.edge_clearance_mm
    if not (math.isfinite(diameter) and 2 <= diameter <= 100
            and math.isfinite(clearance) and 0 <= clearance <= 100):
        raise ValueError(_msg('text.0082'))
    radius = diameter/2
    offset = phantom.radius_mm-radius-clearance
    if centers is None and offset < diameter:
        raise ValueError(_msg('text.0083'))
    placements = (("center", _msg('text.0084'), 0, 0), ("left", _msg('text.0085'), -offset, 0),
                  ("right", _msg('text.0086'), offset, 0), ("top", _msg('text.0087'), 0, -offset),
                  ("bottom", _msg('text.0088'), 0, offset))
    if centers is None:
        centers = [(phantom.column+dx/spacing[1], phantom.row+dy/spacing[0])
                   for _, _, dx, dy in placements]
    else:
        centers = np.asarray(centers, dtype=float)
        if centers.shape != (5, 2) or not np.all(np.isfinite(centers)):
            raise ValueError(_msg('text.0089'))
        physical = (centers - (phantom.column, phantom.row)) * (spacing[1], spacing[0])
        if np.any(np.linalg.norm(physical, axis=1)+radius > phantom.radius_mm+1e-6):
            raise ValueError(_msg('text.0090'))
        for index, point in enumerate(physical):
            if np.any(np.linalg.norm(physical[index+1:]-point, axis=1) < diameter-1e-6):
                raise ValueError(_msg('text.0091'))
    rois = []
    for (key, label, _, _), (column, row) in zip(placements, centers):
        rois.append(_measure_roi(array, spacing, phantom, key, label, column, row, radius))
    center = rois[0]
    rois = tuple(replace(roi, delta_center_hu=roi.mean_hu-center.mean_hu) for roi in rois)
    means, noise = [roi.mean_hu for roi in rois], [roi.std_hu for roi in rois]
    # Additional ROIs are independent samples, not members of the five-ROI
    # uniformity protocol. They must not change its aggregate metrics.
    extra = tuple(replace(_measure_roi(array, spacing, phantom, r.key, r.label,
                         r.column, r.row, r.radius_mm), delta_center_hu=0) for r in extra_rois)
    extra = tuple(replace(r, delta_center_hu=r.mean_hu-center.mean_hu) for r in extra)
    return WaterQaResult(phantom, settings, rois + extra, center.mean_hu, center.std_hu,
                         max(abs(roi.delta_center_hu) for roi in rois[1:]), max(means)-min(means),
                         abs(means[1]-means[2]), abs(means[3]-means[4]), max(noise)-min(noise))


def analyze_water_phantom(pixels, spacing, settings=WaterQaSettings()):
    phantom = detect_water_phantom(pixels, spacing)
    return measure_water_phantom(pixels, spacing, phantom, settings)


BASELINE_KEYS = ("center", "left", "right", "top", "bottom")


def measure_qa_rois(pixels, spacing, phantom, settings, rois, *, detection_issue=""):
    """Remeasure an editable collection by identity, including missing baselines."""
    array, spacing = _validate_input(pixels, spacing)
    baseline = [r for r in rois if r.key in BASELINE_KEYS]
    # Retain the five-point protocol's non-overlap rule for detected water only.
    if phantom is not None:
        for index, roi in enumerate(baseline):
            if any(math.hypot((roi.column-other.column)*spacing[1],
                              (roi.row-other.row)*spacing[0]) < roi.radius_mm+other.radius_mm-1e-6
                   for other in baseline[index+1:]):
                raise ValueError(_msg('text.0091'))
    measured = tuple(_measure_roi(array, spacing, phantom, r.key, r.label,
                                 r.column, r.row, r.radius_mm) for r in rois)
    by_key = {r.key: r for r in measured}
    center = by_key.get("center")
    measured = tuple(replace(r, delta_center_hu=r.mean_hu-center.mean_hu if center else None)
                     for r in measured)
    # A partial protocol or an unidentified object is not a water QA result.
    metrics = (None,) * 7
    if phantom is not None and all(key in by_key for key in BASELINE_KEYS):
        c, left, right, top, bottom = (by_key[key] for key in BASELINE_KEYS)
        means = [by_key[key].mean_hu for key in BASELINE_KEYS]
        noise = [by_key[key].std_hu for key in BASELINE_KEYS]
        metrics = (c.mean_hu, c.std_hu, max(abs(m-c.mean_hu) for m in means[1:]),
                   max(means)-min(means), abs(left.mean_hu-right.mean_hu),
                   abs(top.mean_hu-bottom.mean_hu), max(noise)-min(noise))
    return WaterQaResult(phantom, settings, measured, *metrics, detection_issue=detection_issue)


def create_fallback_rois(pixels, spacing, settings=WaterQaSettings(), *, detection_issue="text.0080"):
    """Seed five physical circles within the image, without claiming a phantom."""
    array, spacing = _validate_input(pixels, spacing)
    diameter, clearance = settings.roi_diameter_mm, settings.edge_clearance_mm
    if not (math.isfinite(diameter) and 2 <= diameter <= 100
            and math.isfinite(clearance) and 0 <= clearance <= 100):
        raise ValueError(_msg('text.0082'))
    radius = diameter/2
    height, width = ((array.shape[i]-1)*spacing[i] for i in range(2))
    offset = min(min(width, height)/4, min(width, height)/2-radius)
    if offset < diameter:
        raise ValueError(_msg('qa.fallbackTooSmall'))
    column, row = (array.shape[1]-1)/2, (array.shape[0]-1)/2
    centers = ((0, 0), (-offset, 0), (offset, 0), (0, -offset), (0, offset))
    rois = tuple(_measure_roi(array, spacing, None, key, _msg(f'text.{84+index:04d}'),
                             column+dx/spacing[1], row+dy/spacing[0], radius)
                 for index, (key, (dx, dy)) in enumerate(zip(BASELINE_KEYS, centers)))
    return measure_qa_rois(array, spacing, None, settings, rois, detection_issue=detection_issue)
