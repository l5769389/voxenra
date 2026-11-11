"""Eligibility and relative stack navigation for side-by-side comparison."""


SYNC_OPERATIONS = ("scroll", "window", "pan", "zoom", "rotate", "flip",
                   "pseudocolor", "invert", "viewport")


def supports_compare(series):
    """Use the same image stacks as 2D; exclude reports and unsupported PET."""
    from voxplane.core.mr import mr_series_error
    from voxplane.core.ct import ct_series_error
    return bool(series and series.instances and not mr_series_error(series)
                and not ct_series_error(series) and all(
        (item.rows or 0) > 0 and (item.columns or 0) > 0
        and (item.modality.upper() != "PT" or item.pet_2d_supported)
        for item in series.instances))


def relative_slice(index, source_count, target_count):
    if source_count <= 1 or target_count <= 1:
        return 0
    fraction = max(0, min(index, source_count - 1)) / (source_count - 1)
    return int(fraction * (target_count - 1) + 0.5)


def supports_mpr_compare(series):
    """Offer reconstructable scalar stacks; the volume loader validates geometry."""
    from voxplane.core.ct import ct_series_error
    if not supports_compare(series) or ct_series_error(series, volume=True):
        return False
    instances = series.instances
    return bool(len(instances) >= 2 and all(
        i.photometric_interpretation.upper() in ("", "MONOCHROME1", "MONOCHROME2")
        and i.image_position_patient is not None
        and i.image_orientation_patient is not None
        and i.pixel_spacing is not None
        for i in instances))

def compatible_patient_space(first, second):
    """Frame of Reference is necessary; matching demographics alone is not."""
    return bool(first.frame_of_reference_uid and
                first.frame_of_reference_uid == second.frame_of_reference_uid and
                first.study_uid and first.study_uid == second.study_uid and
                first.patient_id == second.patient_id)


def plane_basis(geometry):
    import numpy as np
    position, orientation, spacing, rows, columns = geometry
    if position is None or orientation is None or spacing is None or not rows or not columns:
        return None
    origin, u, v = np.array(position, float), np.array(orientation[:3], float), np.array(orientation[3:], float)
    if not np.isfinite([*origin, *u, *v, spacing.row, spacing.column]).all():
        return None
    if (spacing.row <= 0 or spacing.column <= 0 or
        not np.allclose([u@u, v@v, u@v], [1, 1, 0], atol=1e-4)):
        return None
    return origin, u * spacing.column, v * spacing.row, np.cross(u, v)


def plane_center(geometry):
    basis = plane_basis(geometry)
    if basis is None: return None
    origin, u, v, _ = basis
    return origin + u * ((geometry[4]-1)/2) + v * ((geometry[3]-1)/2)


def nearest_patient_slice(point, geometries, source_normal=None):
    """Nearest plane within the acquired slab; never clamp a distant point.

    Scroll linking only applies to parallel stacks. Explicit point navigation
    may cross orientations, provided the point lies inside the target image.
    """
    import numpy as np
    if point is None or not geometries: return None
    bases = [plane_basis(g) for g in geometries]
    if any(b is None for b in bases): return None
    normal = bases[0][3]
    if source_normal is not None and abs(np.dot(source_normal, normal)) < .999:
        return None
    if any(abs(np.dot(b[3], normal)) < .999 for b in bases): return None
    positions = np.array([b[0] @ normal for b in bases])
    unique = np.unique(np.round(positions, 5))
    if len(unique) != len(positions): return None
    tolerance = float(np.median(np.diff(np.sort(unique)))) / 2 if len(unique)>1 else .5
    projection = np.asarray(point) @ normal
    if projection < positions.min()-tolerance or projection > positions.max()+tolerance: return None
    index = int(np.argmin(np.abs(positions-projection)))
    origin, u, v, _ = bases[index]
    delta = np.asarray(point)-origin
    column, row = delta@u/(u@u), delta@v/(v@v)
    if not (-.5 <= column <= geometries[index][4]-.5 and -.5 <= row <= geometries[index][3]-.5):
        return None
    return index


def reference_line(source, target):
    """Intersection of source plane and target rectangle in target pixels."""
    import numpy as np
    a, b = plane_basis(source), plane_basis(target)
    if a is None or b is None: return None
    origin, u, v, _ = b
    normal = a[3]
    x, y, c = float(normal@u), float(normal@v), float(normal@(origin-a[0]))
    if abs(x)+abs(y) < 1e-8: return None
    width, height = target[4]-1, target[3]-1
    candidates = []
    if abs(y)>1e-8:
        candidates += [(0., -c/y), (float(width), -(c+x*width)/y)]
    if abs(x)>1e-8:
        candidates += [(-c/x, 0.), (-(c+y*height)/x, float(height))]
    points=[]
    for p in candidates:
        if (-1e-6 <= p[0] <= width+1e-6 and -1e-6 <= p[1] <= height+1e-6
            and not any(np.linalg.norm(np.asarray(p)-q)<1e-6 for q in points)):
            points.append(p)
    return (*points[0], *points[1]) if len(points)==2 else None
