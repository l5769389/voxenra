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
    if not np.any(np.isfinite(array)):
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
        values = array[(disk <= (phantom.radius_mm*0.7)**2) & np.isfinite(array)]
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
    if not np.all(np.isfinite(values)):
        raise ValueError(_msg("qa.invalidSamples"))
    if len(values) < 16:
        raise ValueError(_msg('text.0093'))
    # Do not reject outlier HU samples or drop non-water pixels here: doing
    # so would hide image artefacts and underestimate noise/nonuniformity.
    return WaterQaRoi(key, label, column, row, radius, len(values),
                          len(values)*spacing[0]*spacing[1], float(values.mean()),
                          float(values.std(ddof=0)), float(values.min()), float(values.max()), 0)


def resolved_settings(settings, phantom=None):
    diameter = phantom.radius_mm*2 if phantom else 200.
    return replace(settings,
        roi_diameter_mm=diameter*.1 if settings.roi_diameter_mm is None else settings.roi_diameter_mm,
        noise_diameter_mm=diameter*.4 if settings.noise_diameter_mm is None else settings.noise_diameter_mm)


def noise_roi(array, spacing, phantom, diameter):
    return replace(_measure_roi(array, spacing, phantom, "noise", _msg("qa.noiseRoi"),
        phantom.column, phantom.row, diameter/2), group="noise", delta_center_hu=None)


def measure_water_phantom(pixels, spacing, phantom, settings=WaterQaSettings(), *, centers=None, extra_rois=()):
    """Sample five ROIs, optionally at manually adjusted (column, row) centers."""
    array, spacing = _validate_input(pixels, spacing)
    settings = resolved_settings(settings, phantom)
    diameter, clearance = settings.roi_diameter_mm, settings.edge_clearance_mm
    if not (math.isfinite(diameter) and diameter >= 2
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
    rois.append(noise_roi(array, spacing, phantom, settings.noise_diameter_mm))
    return measure_qa_rois(array, spacing, phantom, settings, tuple(rois)+tuple(extra_rois))


def analyze_water_phantom(pixels, spacing, settings=WaterQaSettings()):
    phantom = detect_water_phantom(pixels, spacing)
    return measure_water_phantom(pixels, spacing, phantom, settings)


BASELINE_KEYS = ("center", "left", "right", "top", "bottom")


def measure_qa_rois(pixels, spacing, phantom, settings, rois, *, detection_issue=""):
    """Remeasure an editable collection by identity, including missing baselines."""
    array, spacing = _validate_input(pixels, spacing)
    settings = resolved_settings(settings, phantom)
    baseline = [r for r in rois if r.key in BASELINE_KEYS]
    # Retain the five-point protocol's non-overlap rule for detected water only.
    if phantom is not None:
        for index, roi in enumerate(baseline):
            if any(math.hypot((roi.column-other.column)*spacing[1],
                              (roi.row-other.row)*spacing[0]) < roi.radius_mm+other.radius_mm-1e-6
                   for other in baseline[index+1:]):
                raise ValueError(_msg('text.0091'))
    measured = []
    for r in rois:
        if r.group == "air" and phantom is not None and math.hypot(
                (r.column-phantom.column)*spacing[1], (r.row-phantom.row)*spacing[0]) < phantom.radius_mm+r.radius_mm:
            raise ValueError(_msg("qa.airOverlapsPhantom"))
        sample = _measure_roi(array, spacing, None if r.group == "air" else phantom,
                              r.key, r.label, r.column, r.row, r.radius_mm)
        measured.append(replace(sample, group=r.group))
    by_key = {r.key: r for r in measured}
    center, noise = by_key.get("center"), by_key.get("noise")
    measured = tuple(replace(r, delta_center_hu=r.mean_hu-center.mean_hu
                     if center and r.group == "uniformity" else None) for r in measured)
    water_ct = center.mean_hu if phantom is not None and center else None
    noise_hu = noise.std_hu if phantom is not None and noise else None
    metrics = (water_ct, noise_hu) + (None,) * 5
    if phantom is not None and all(key in by_key for key in BASELINE_KEYS):
        c, left, right, top, bottom = (by_key[key] for key in BASELINE_KEYS)
        means = [by_key[key].mean_hu for key in BASELINE_KEYS]
        stds = [by_key[key].std_hu for key in BASELINE_KEYS]
        metrics = (water_ct, noise_hu, max(abs(m-c.mean_hu) for m in means[1:]),
                   max(means)-min(means), abs(left.mean_hu-right.mean_hu),
                   abs(top.mean_hu-bottom.mean_hu), max(stds)-min(stds))
    return WaterQaResult(phantom, settings, measured, *metrics, detection_issue=detection_issue,
                         noise_percent=noise_hu/10 if noise_hu is not None else None, protocol_version=2)


def create_fallback_rois(pixels, spacing, settings=WaterQaSettings(), *, detection_issue="text.0080"):
    """Seed five physical circles within the image, without claiming a phantom."""
    array, spacing = _validate_input(pixels, spacing)
    settings = resolved_settings(settings)
    diameter, clearance = settings.roi_diameter_mm, settings.edge_clearance_mm
    if not (math.isfinite(diameter) and diameter >= 2
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


def maximum_roi_diameter(shape, spacing, phantom, rois):
    """Largest common diameter at the existing centers, in physical mm."""
    sy, sx = spacing
    if not rois:
        return min((shape[0]-1)*sy, (shape[1]-1)*sx)/4
    limits = []
    for roi in rois:
        limits.extend((2*roi.column*sx, 2*(shape[1]-1-roi.column)*sx,
                       2*roi.row*sy, 2*(shape[0]-1-roi.row)*sy))
        if phantom is not None:
            distance = math.hypot((roi.column-phantom.column)*sx,
                                  (roi.row-phantom.row)*sy)
            clearance = (distance - phantom.radius_mm if roi.group == "air"
                         else phantom.radius_mm - distance)
            limits.append(2*clearance)
    baseline = [r for r in rois if r.key in BASELINE_KEYS]
    if phantom is not None:
        limits.extend(math.hypot((a.column-b.column)*sx, (a.row-b.row)*sy)
                      for i, a in enumerate(baseline) for b in baseline[i+1:])
    return max(0., min(limits))


def find_external_air_roi(pixels, spacing, phantom, diameter_mm=20.):
    """Conservative placement hint, not a filter on measured samples.

    Require an identified phantom, finite surrounding air and clearance from
    tissue, image edges and padding. Rank by geometry, never by the lowest SD
    or the mean closest to -1000. Constant filled backgrounds are ambiguous.
    """
    array, (sy, sx) = _validate_input(pixels, spacing)
    if phantom is None or not math.isfinite(diameter_mm) or diameter_mm < 2:
        return None
    radius, margin = diameter_mm/2, 3.
    rows, columns = array.shape
    yy, xx = np.ogrid[:rows, :columns]
    distance = np.hypot((xx-phantom.column)*sx, (yy-phantom.row)*sy)
    bad = (~np.isfinite(array) | (array < -1200) | (array > -700)
           | (distance < phantom.radius_mm+margin))
    air_values = array[~bad]
    if not air_values.size or np.ptp(air_values) < 1:
        return None  # Common constant-fill case; avoid scanning every candidate.
    # Bounding rectangles are stricter than disks, avoiding a large convolution
    # or any extra dependency while rejecting shells, supports and invalid FOV.
    integral = np.pad(bad.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    rx, ry = (radius+margin)/sx, (radius+margin)/sy
    xs = np.arange(math.ceil(rx), columns-math.ceil(rx), max(1, round(3/sx)))
    ys = np.arange(math.ceil(ry), rows-math.ceil(ry), max(1, round(3/sy)))
    if not len(xs) or not len(ys):
        return None
    x, y = np.meshgrid(xs, ys)
    x, y = x.ravel(), y.ravel()
    x0, x1 = np.floor(x-rx).astype(int), np.ceil(x+rx).astype(int)+1
    y0, y1 = np.floor(y-ry).astype(int), np.ceil(y+ry).astype(int)+1
    good = (integral[y1,x1]-integral[y0,x1]-integral[y1,x0]+integral[y0,x0]) == 0
    x, y = x[good], y[good]
    clearance = np.minimum.reduce((x*sx, (columns-1-x)*sx, y*sy, (rows-1-y)*sy,
        np.hypot((x-phantom.column)*sx, (y-phantom.row)*sy)-phantom.radius_mm))
    for i in np.argsort(-clearance, kind="stable"):
        roi = _measure_roi(array, (sy,sx), None, 'air-1', _msg('qa.airRoi', number=1), x[i], y[i], radius)
        # Unmarked uniform fill cannot be distinguished safely from real air.
        if roi.std_hu >= .25 and roi.maximum_hu-roi.minimum_hu >= 1:
            return replace(roi, group='air', delta_center_hu=None)
    return None


def resize_qa_rois(previous, settings, spacing):
    """Change only requested geometry, retaining deleted ROIs and edited centers."""
    settings = resolved_settings(settings, previous.phantom)
    rois = previous.rois
    # Old saved results keep their numbers until explicitly recalculated.
    if previous.protocol_version < 2 and previous.phantom is not None:
        c = next((r for r in rois if r.key == "center"), None)
        if c is not None:
            rois += (replace(c, key="noise", label=_msg("qa.noiseRoi"), group="noise",
                             radius_mm=settings.noise_diameter_mm/2),)
    fields = {"uniformity": "roi_diameter_mm", "noise": "noise_diameter_mm", "air": "air_diameter_mm"}
    rois = tuple(replace(r, radius_mm=getattr(settings, fields[r.group])/2)
                 if getattr(settings, fields[r.group]) != getattr(previous.settings, fields[r.group]) else r
                 for r in rois)
    phantom = previous.phantom
    if phantom is not None and settings.edge_clearance_mm != previous.settings.edge_clearance_mm:
        sy, sx = spacing
        adjusted = []
        for r in rois:
            if r.key in BASELINE_KEYS[1:]:
                dx, dy = (r.column-phantom.column)*sx, (r.row-phantom.row)*sy
                distance = math.hypot(dx, dy)
                offset = phantom.radius_mm-r.radius_mm-settings.edge_clearance_mm
                if distance <= 1e-9 or offset < 0:
                    raise ValueError(_msg('text.0083'))
                r = replace(r, column=phantom.column+dx/distance*offset/sx,
                            row=phantom.row+dy/distance*offset/sy)
            adjusted.append(r)
        rois = tuple(adjusted)
    return rois
