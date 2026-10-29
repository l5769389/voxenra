import numpy as np
import pytest

from test_mpr_sampling_precision import reference_sample


def sampler():
    from qt_dicom_viewer.core.volume_sampling import sample_volume
    return sample_volume


@pytest.mark.parametrize("strided", [False, True])
@pytest.mark.parametrize("shape", [(3, 4, 5), (1, 4, 5), (3, 1, 5), (3, 4, 1)])
def test_public_sampler_matches_scalar_reference_and_leaves_source_unchanged(strided, shape):
    pixels = np.arange(np.prod(shape), dtype=np.float32).reshape(shape) - 40
    pixels.ravel()[::3] = np.nan
    if strided:
        pixels = pixels[::-1, :, ::-1]
    before = pixels.copy()
    points = np.random.default_rng(17).random((75, 3)) * (np.array(shape) - 1)
    actual = sampler()(pixels, *points.T)
    np.testing.assert_allclose(actual, reference_sample(pixels, points), atol=1e-5)
    np.testing.assert_array_equal(pixels, before)
    assert actual.dtype == np.float32


def test_nonfinite_coordinates_and_outside_neighbours_remain_missing():
    pixels = np.arange(8, dtype=np.float32).reshape(2, 2, 2)
    points = np.array([[np.nan, 0, 0], [0, np.inf, 0], [0, 0, -np.inf],
                       [-1, 0, 0], [2, 0, 0], [.5, .5, .5]])
    with np.errstate(all="raise"):
        actual = sampler()(pixels, *points.T)
    np.testing.assert_allclose(actual, [np.nan] * 5 + [3.5], equal_nan=True)


def test_broadcasting_and_missing_weight_renormalization():
    pixels = np.array([[[2., np.nan], [6., 8.]]], dtype=np.float32)
    actual = sampler()(pixels, 0., np.array([[0.], [1.]]), np.array([[0., .5, 1.]]))
    np.testing.assert_allclose(actual, [[2, 2, np.nan], [6, 7, 8]], equal_nan=True)


@pytest.mark.parametrize("pixels", [np.zeros((2, 2)), np.zeros((0, 2, 2)),
                                    np.full((2, 2, 2), "x"), np.zeros((2, 2, 2), complex)])
def test_invalid_volume_is_a_clear_sampling_error(pixels):
    from qt_dicom_viewer.core.volume_sampling import VolumeSamplingError
    with pytest.raises(VolumeSamplingError):
        sampler()(pixels, [0.], [0.], [0.])


def test_mpr_keeps_its_existing_error_contract_for_invalid_volume():
    from qt_dicom_viewer.core.mpr_reslicer import MprReslicer, MprResliceError
    with pytest.raises(MprResliceError):
        MprReslicer._trilinear_sample(np.zeros((2, 2)), np.array([0.]), np.array([0.]), np.array([0.]))
