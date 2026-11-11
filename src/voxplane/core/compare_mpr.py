"""Geometric coverage and physical display scaling for MPR comparison."""
from itertools import product
import numpy as np


def plane_intersects_volume(volume, plane, slab_thickness_mm=0.0):
    """Test the finite sampled plane/slab against the source voxel-center box.

    Separating axes include both boxes' axes and their pairwise cross products.
    This handles oblique planes, an off-volume crosshair with a valid section,
    finite output grids and slabs without inspecting intensity or allocating voxels.
    """
    source = np.asarray([(*p, 1.) for p in product(
        (0, volume.slice_count - 1), (0, volume.rows - 1), (0, volume.columns - 1))])
    half = max(0., slab_thickness_mm) / (2 * plane.navigation_spacing)
    section = np.asarray([(*p, 1.) for p in product(
        (-half, half), (0, plane.rows - 1), (0, plane.columns - 1))])
    source_matrix, section_matrix = volume.voxel_to_patient, plane.image_index_to_patient
    source = (source @ source_matrix.T)[:, :3]
    section = (section @ section_matrix.T)[:, :3]
    a, b = source_matrix[:3, :3].T, section_matrix[:3, :3].T
    a, b = a / np.linalg.norm(a, axis=1)[:, None], b / np.linalg.norm(b, axis=1)[:, None]
    axes = np.concatenate((a, b, np.cross(a[:, None, :], b[None, :, :]).reshape(-1, 3)))
    axes = axes[np.linalg.norm(axes, axis=1) > 1e-10]
    axes /= np.linalg.norm(axes, axis=1)[:, None]
    # Subtract a shared origin to retain precision for large patient coordinates.
    origin = source[0].copy()
    source, section = (source - origin) @ axes.T, (section - origin) @ axes.T
    return not bool(np.any(source.max(axis=0) < section.min(axis=0) - 1e-5)
                    or np.any(section.max(axis=0) < source.min(axis=0) - 1e-5))


def matched_zooms(first_fit, second_fit, pixels_per_mm):
    """Keep the same physical scale within both viewports' supported zoom range."""
    lower, upper = .1 * max(first_fit, second_fit), 20. * min(first_fit, second_fit)
    if lower > upper:
        return None
    scale = max(lower, min(pixels_per_mm, upper))
    return scale / first_fit, scale / second_fit
