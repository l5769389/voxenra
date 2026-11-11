"""Simple open/closed paths and ROI masks in image pixel-center coordinates."""

import math
from functools import lru_cache
import numpy as np


def polygon_area(points):
    p = np.asarray([(v.column, v.row) for v in points], dtype=float)
    if len(p) < 3:
        return 0.0
    return (
        abs(
            float(
                np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))
            )
        )
        / 2
    )


def simple_polygon(points):
    """Reject crossings/touches between nonadjacent edges; area stays unambiguous."""
    return simple_path(points, closed=True) and polygon_area(points) > 1e-6


def simple_path(points, *, closed=False):
    """Reject crossings, nonadjacent touches and adjacent retraced segments."""
    p = np.asarray([(v.column, v.row) for v in points], dtype=float)
    if (len(p) < (3 if closed else 2) or len(p) > 16384
            or not np.isfinite(p).all()):
        return False
    q = np.roll(p, -1, axis=0) if closed else p[1:]
    p = p if closed else p[:-1]
    n = len(p)
    cross = lambda a, b: a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    delta = q - p
    if np.any(np.sum(delta * delta, axis=1) <= 1e-18):
        return False
    before = np.roll(delta, 1, axis=0) if closed else delta[:-1]
    after = delta if closed else delta[1:]
    if np.any((np.abs(cross(before, after)) <= 1e-12)
              & (np.sum(before * after, axis=1) < 0)):
        return False
    # Sweep bounding boxes in X. Smooth boundaries may contain thousands of
    # short segments; only overlapping nonadjacent segments need exact tests.
    lower, upper = np.minimum(p, q), np.maximum(p, q)
    x0, y0 = lower.T.tolist()
    x1, y1 = upper.T.tolist()
    active = []
    for i in sorted(range(n), key=x0.__getitem__):
        active = [j for j in active if x1[j] + 1e-9 >= x0[i]]
        js = [j for j in active
              if abs(i-j) != 1 and not (closed and abs(i-j) == n-1)
              and max(y0[i], y0[j]) <= min(y1[i], y1[j]) + 1e-9]
        active.append(i)
        if not js:
            continue
        a, b, c, d = p[i], q[i], p[js], q[js]
        hit = (
            (cross(b - a, c - a) * cross(b - a, d - a) <= 1e-12)
            & (cross(d - c, a - c) * cross(d - c, b - c) <= 1e-12)
        )
        if np.any(hit):
            return False
    return True


def contains_point(points, x, y):
    if len(points) < 3:
        return False
    inside = False
    for a, b in zip(points, (*points[1:], points[0])):
        if (a.row > y) != (b.row > y):
            crossing = a.column + (y - a.row) * (b.column - a.column) / (b.row - a.row)
            if x < crossing:
                inside = not inside
    return inside


def polygon_mask(points, x0, x1, y0, y1):
    """Scanline fill including boundary pixel centers, bounded by the image crop."""
    mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=bool)
    p = np.asarray([(v.column, v.row) for v in points], dtype=float)
    q = np.roll(p, -1, axis=0)
    for row, y in enumerate(range(y0, y1 + 1)):
        crossing = (p[:, 1] > y) != (q[:, 1] > y)
        a, b = p[crossing], q[crossing]
        xs = np.sort(
            a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
        )
        for left, right in zip(xs[::2], xs[1::2]):
            lo, hi = max(x0, math.ceil(left - 1e-9)), min(x1, math.floor(right + 1e-9))
            if lo <= hi:
                mask[row, lo - x0 : hi - x0 + 1] = True
        # Horizontal edges (including upper/lower bounds) belong to the ROI.
        horizontal = (abs(p[:, 1] - y) < 1e-9) & (abs(q[:, 1] - y) < 1e-9)
        for a, b in zip(p[horizontal], q[horizontal]):
            lo, hi = (
                max(x0, math.ceil(min(a[0], b[0]))),
                min(x1, math.floor(max(a[0], b[0]))),
            )
            if lo <= hi:
                mask[row, lo - x0 : hi - x0 + 1] = True
        for a in p[abs(p[:, 1] - y) < 1e-9]:
            x = round(float(a[0]))
            if x0 <= x <= x1 and abs(x - a[0]) < 1e-9:
                mask[row, x - x0] = True
    return mask


def roi_outline(points, smooth=False):
    """One boundary for display, statistics, picking, reports and segmentation."""
    return _roi_outline(tuple(points), smooth)


@lru_cache(maxsize=16)
def _roi_outline(points, smooth):
    if not smooth:
        return points
    from voxplane.core.curve_geometry import sample_closed_curve
    # Keep existing safe splines unchanged. Tighten only contours whose cubic
    # handles overshoot into another span (including a loop within one span).
    # Validate the actual sampled boundary used by drawing and all measurements.
    if len(points) > 4096 or not simple_polygon(points):
        return ()
    for tension in (1.0, .5, .25, .125, .0625, .03125, .015625):
        boundary = sample_closed_curve(points, tension=tension)
        if simple_polygon(boundary):
            return boundary
    # A simple control polygon is the bounded, intersection-free limiting shape.
    # Never display or measure an intersecting smoothing result.
    return points
