"""Open interpolating Catmull–Rom curves; controls remain distinct from samples."""
import math
from functools import lru_cache
import numpy as np
from voxplane.model.image_geometry import ImagePoint


def sample_curve(points, subdivisions=128):
    """Bounded, intersection-free interpolating path shared by all consumers."""
    return _safe_curve(tuple(points), subdivisions)


@lru_cache(maxsize=16)
def _safe_curve(points, subdivisions):
    from voxplane.core.freehand_roi import simple_path
    if (len(points) > 4096 or subdivisions < 1
            or not all(math.isfinite(v) for p in points for v in (p.column, p.row))):
        return ()
    if len(points) < 2:
        return points
    if not simple_path(points):
        return ()  # Crossing clicks cannot be repaired without changing their order.
    if len(points) == 2:
        return points
    # Keep rendering and topology checks bounded even for imported dense paths.
    subdivisions = min(subdivisions, 16383 // (len(points) - 1))
    for tension in (1.0, .5, .25, .125, .0625, .03125, .015625):
        samples = _sample_open_curve(points, subdivisions, tension)
        if simple_path(samples):
            return samples
    return points  # The simple polyline is the zero-handle limiting shape.


def _sample_open_curve(points, subdivisions, tension):
    """Uniform cubic with reflected endpoints and adjustable Bezier handles."""
    p = np.asarray([(v.column, v.row) for v in points], dtype=float)
    extended = np.vstack((2 * p[0] - p[1], p, 2 * p[-1] - p[-2]))
    t = np.arange(subdivisions, dtype=float)[:, None] / subdivisions
    samples = []
    for i in range(len(p) - 1):
        a, b, c, d = extended[i:i + 4]
        v = 0.5 * (2*b + (-a+c)*t + (2*a-5*b+4*c-d)*t*t + (-a+3*b-3*c+d)*t*t*t)
        if tension != 1.0:
            zero_handles = b + (c-b)*(3*t*t - 2*t*t*t)
            v = zero_handles + tension*(v-zero_handles)
        samples.extend(ImagePoint(float(x), float(y)) for x, y in v)
    samples.append(points[-1])
    return tuple(samples)


def curve_length_mm(points, row_spacing, column_spacing):
    if not all(math.isfinite(v) and v > 0 for v in (row_spacing, column_spacing)):
        return 0.0
    samples = sample_curve(points)
    return sum(math.hypot((b.column-a.column)*column_spacing, (b.row-a.row)*row_spacing)
               for a, b in zip(samples, samples[1:]))


def sample_closed_curve(points, tolerance=0.001, *, tension=1.0):
    """Flatten a periodic interpolating cubic to within 0.001 image pixels.

    Each Catmull–Rom span is converted to a cubic Bezier and subdivided until
    both inner controls are within tolerance of its chord. The closing endpoint
    is omitted so downstream polygon routines close exactly once. ``tension``
    scales both Bezier handles to tighten an unsafe overshooting contour. Pathological
    contours are bounded and rejected, never silently simplified.
    """
    if not 3 <= len(points) <= 4096:
        return ()
    p = np.asarray([(v.column, v.row) for v in points], dtype=float)
    if not np.isfinite(p).all():
        return ()
    output = []

    def distance_squared(point, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx*dx + dy*dy
        t = max(0.0, min(1.0, ((point[0]-a[0])*dx + (point[1]-a[1])*dy)/length)) if length else 0.0
        return (point[0]-a[0]-t*dx)**2 + (point[1]-a[1]-t*dy)**2

    def midpoint(a, b):
        return ((a[0]+b[0])/2, (a[1]+b[1])/2)

    for i in range(len(p)):
        a, b, c, d = (p[(i+j) % len(p)] for j in (-1, 0, 1, 2))
        stack = [(tuple(b), tuple(b+tension*(c-a)/6), tuple(c-tension*(d-b)/6), tuple(c), 0)]
        while stack:
            a, b, c, d, depth = stack.pop()
            error = max(distance_squared(b, a, d), distance_squared(c, a, d))
            if error <= tolerance*tolerance:
                output.append(ImagePoint(float(a[0]), float(a[1])))
                if len(output) > 16384:
                    return ()
            elif depth >= 16:
                return ()
            else:
                ab, bc, cd = midpoint(a, b), midpoint(b, c), midpoint(c, d)
                abc, bcd = midpoint(ab, bc), midpoint(bc, cd)
                mid = midpoint(abc, bcd)
                stack.append((mid, bcd, cd, d, depth+1))
                stack.append((a, ab, abc, mid, depth+1))
    return tuple(output)
