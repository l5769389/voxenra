"""Ramp geometry, profile sampling and finite ROI checks with analytic oracles."""
import math

import numpy as np
import pytest

from voxplane.core.ramp_fwhm import compute_ramp_fwhm, ramp_slice_thickness


@pytest.mark.parametrize('angle', [23, 45])
@pytest.mark.parametrize('direction', ['x', 'y'])
@pytest.mark.parametrize('method', ['gaussian', 'direct_fft'])
def test_gaussian_ramp_recovers_one_mm_for_anisotropic_pixels(angle, direction, method):
    spacing = .13 if direction == 'x' else .2
    sigma = 1 / math.tan(math.radians(angle)) / math.sqrt(8 * math.log(2))
    position = (np.arange(101) - 50) * spacing
    profile = 70 + 1000 * np.exp(-.5 * (position / sigma)**2)
    pixels = np.tile(profile, (5, 1))
    if direction == 'y':
        pixels = pixels.T
    result = compute_ramp_fwhm(pixels, .2, .13, direction=direction, analysis_method=method)
    assert ramp_slice_thickness(result.fwhm, angle) == pytest.approx(1, rel=.008)
    assert result.background == pytest.approx(70, abs=.001)
    assert result.spacing == spacing
    assert result.analysis_method == ('gaussian' if method == 'gaussian' else 'half_height')
    assert not result.warnings


def test_half_height_interpolates_plateau_and_averages_selected_rows():
    profile = np.array([0, 0, 0, 1, 4, 4, 1, 0, 0, 0], dtype=float)
    pixels = np.stack([80 + profile, 80 + profile * 3])
    original = pixels.copy()
    result = compute_ramp_fwhm(pixels, .7, .3, analysis_method='direct_fft')
    np.testing.assert_allclose(result.profile, profile * 2)
    assert result.fwhm == pytest.approx(.7)
    assert ramp_slice_thickness(result.fwhm, 23) == pytest.approx(.29713237134672334)
    np.testing.assert_array_equal(pixels, original)


@pytest.mark.parametrize('method', ['gaussian', 'direct_fft'])
def test_truncated_profile_does_not_extrapolate_slice_thickness(method):
    pixels = np.array([[0, 0, 0, 0, 0, 1, 2, 4, 6, 8, 10, 12]])
    result = compute_ramp_fwhm(pixels, 1, 1, analysis_method=method)
    assert result.fwhm is None
    assert ramp_slice_thickness(result.fwhm, 23) is None
    assert any('交点不完整' in w for w in result.warnings)


@pytest.mark.parametrize('roi, direction', [(np.zeros((3, 7)), 'x'), (np.zeros((7, 3)), 'y')])
def test_profile_requires_eight_pixels_along_selected_direction(roi, direction):
    with pytest.raises(ValueError, match='8'):
        compute_ramp_fwhm(roi, 1, 1, direction=direction)


@pytest.mark.parametrize('pixels', [np.zeros((8, 8)), np.full((8, 8), np.nan), np.full((8, 8), np.inf)])
def test_invalid_signal_cannot_produce_thickness(pixels):
    with pytest.raises(ValueError):
        compute_ramp_fwhm(pixels, 1, 1)


@pytest.mark.parametrize('value', [None, -1, 0, float('inf'), float('nan')])
def test_missing_or_invalid_fwhm_has_no_thickness(value):
    assert ramp_slice_thickness(value, 23) is None


@pytest.mark.parametrize('angle', [0, 90, -23, float('nan'), float('inf')])
def test_invalid_angle_rejected(angle):
    with pytest.raises(ValueError):
        ramp_slice_thickness(1, angle)


@pytest.mark.parametrize('method', ['direct_fft', 'gaussian'])
def test_multiple_half_height_lobes_are_flagged_without_bridging_the_dip(method):
    profile = np.array([0, 0, 0, 1, 4, 8, 10, 8, 4, 3, 6, 5, 1, 0, 0, 0])
    result = compute_ramp_fwhm(profile[None, :], .8, .2, analysis_method=method)
    assert any('多次穿越半高' in warning for warning in result.warnings)
    if method == 'direct_fft':
        # Interpolate the two crossings surrounding the global peak;
        # do not silently bridge to the second lobe to obtain a wider result.
        assert result.fwhm == pytest.approx(.7)


@pytest.mark.parametrize('method', ['direct_fft', 'gaussian'])
def test_width_is_invariant_to_intensity_scale_and_offset(method):
    x = np.arange(61) - 30
    profile = 37 + 450 * np.exp(-.5 * ((x - .3) / 4.3)**2)
    base = compute_ramp_fwhm(profile[None, :], .8, .2, analysis_method=method)
    shifted = compute_ramp_fwhm((profile * 2.7 - 1024)[None, :], .8, .2, analysis_method=method)
    assert shifted.fwhm == pytest.approx(base.fwhm, rel=1e-10)


def test_gaussian_plot_retains_the_fitted_baseline():
    x = np.arange(41) - 20
    profile = 75 + 800 * np.exp(-.5 * ((x - .2) / 7.2)**2)
    result = compute_ramp_fwhm(profile[None, :], .8, .2)
    # End samples still contain a Gaussian tail. The free fit baseline
    # must be applied to the plotted raw curve, not discarded.
    reconstructed = np.array(result.fitted) + result.fitted_background + result.background
    np.testing.assert_allclose(reconstructed, profile, atol=1)
    assert result.background + result.fitted_background == pytest.approx(75, abs=1)
    assert result.fwhm == pytest.approx(7.2 * .2 * math.sqrt(8 * math.log(2)), rel=.005)
