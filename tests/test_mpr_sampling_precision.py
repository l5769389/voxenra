"""Accuracy of the shared blocked CT/PET sampler, independent of its fast path."""
from itertools import product

import numpy as np
import pytest

from voxplane.core.mpr_reslicer import MprReslicer
from voxplane.core.mpr_rotation import rotate_mpr_state_3d
from voxplane.model import MprPlane
from voxplane.model.dicom_core import MprFrame, MprState
from test_mpr_reslicer import _volume


def reference_sample(volume, points):
    """Scalar eight-corner definition with finite-weight renormalization."""
    output = []
    for point in points:
        if any(v < -1e-6 or v > n - 1 + 1e-6 for v, n in zip(point, volume.shape)):
            output.append(np.nan)
            continue
        point = np.clip(point, 0, np.array(volume.shape) - 1)
        low = np.floor(point).astype(int)
        fraction = point - low
        total = support = 0.
        for corner in product((0, 1), repeat=3):
            index = tuple(min(i + j, n - 1) for i, j, n in zip(low, corner, volume.shape))
            weight = np.prod([f if j else 1 - f for f, j in zip(fraction, corner)])
            value = float(volume[index])
            if np.isfinite(value) and weight > 0:
                total += weight * value
                support += weight
        output.append(total / support if support else np.nan)
    return np.asarray(output, dtype=np.float32)


@pytest.mark.parametrize('shape', [(7, 9, 11), (1, 9, 11), (7, 1, 11), (7, 9, 1)])
@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('strided', [False, True])
def test_interpolation_matches_scalar_reference_at_edges_and_missing_voxels(shape, missing, strided):
    rng = np.random.default_rng(508)
    pixels = rng.uniform(-1024, 3000, shape).astype(np.float32)
    if missing:
        pixels.ravel()[::5] = np.nan
        pixels.ravel()[1::13] = np.inf
        pixels.ravel()[2::17] = -np.inf
    if strided:
        pixels = pixels[::-1, :, ::-1]
    points = rng.uniform(0, 1, (300, 3)) * (np.array(shape) - 1)
    edges = np.asarray(list(product(*[(0., n - 1.) for n in shape])))
    points = np.concatenate((points, edges, edges - 5e-7, edges + 5e-7,
                             edges - 2e-6, edges + 2e-6))
    actual = MprReslicer._trilinear_sample(pixels, *points.T)
    np.testing.assert_allclose(actual, reference_sample(pixels, points), rtol=2e-6, atol=1e-6)
    assert actual.dtype == np.float32 and actual.flags.c_contiguous


@pytest.mark.parametrize('scale', [1e-8, 1., 1e30])
def test_interpolation_preserves_small_pet_values_and_large_signed_values(scale):
    pixels = np.asarray([[[-1, 2], [4, -8]], [[-2, 3], [9, -12]]], dtype=np.float32) * scale
    points = np.random.default_rng(602).uniform(0, 1, (200, 3))
    actual = MprReslicer._trilinear_sample(pixels, *points.T)
    np.testing.assert_allclose(actual, reference_sample(pixels, points), rtol=2e-6, atol=scale * 1e-6)


@pytest.mark.parametrize('plane', list(MprPlane))
def test_blocked_oblique_plane_matches_physical_coordinate_reference(plane):
    rng = np.random.default_rng(7)
    volume = _volume(rng.uniform(-1000, 3000, (71, 79, 601)).astype(np.float32),
                     slice_spacing=1.7, row_spacing=.8, column_spacing=.6,
                     origin=(13., -29., 7.))
    reslicer = MprReslicer()
    state = rotate_mpr_state_3d(MprState(MprFrame.standard_lps(volume.geometry.center_patient)),
                                (1., 2., 3.), .37)
    result = reslicer.reslice(volume, plane, state.frame)
    geometry = result.geometry
    positions = np.column_stack((rng.integers(0, geometry.rows, 250),
                                 rng.integers(0, geometry.columns, 250)))
    # Sample across the row blocks as well as corners; map directly from the
    # geometry so block offsets cannot silently shift anatomy.
    positions = np.concatenate((positions, [[0, 0], [geometry.rows - 1, geometry.columns - 1]]))
    indices = np.column_stack((np.zeros(len(positions)), positions, np.ones(len(positions))))
    points = (geometry.image_index_to_voxel(volume.geometry) @ indices.T)[:3].T
    actual = result.modality_pixels[positions[:, 0], positions[:, 1]]
    np.testing.assert_allclose(actual, reference_sample(volume.modality_pixels, points),
                               rtol=2e-6, atol=1e-5)
    assert result.modality_pixels.flags.c_contiguous
