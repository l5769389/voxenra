"""Physical support must retain weak wide tails, not just the central peak."""
import math

import numpy as np
import pytest

from voxplane.core.bead_mtf import compute_point_source_mtf, compute_mtf_with_context


def wide_source(amplitude, *, slope=False, center=(128., 128.), size=257):
    yy, xx = np.mgrid[:size, :size]
    radius2 = (xx-center[0])**2 + (yy-center[1])**2
    pixels = 100 + 2000*(np.exp(-radius2/(2*1.5**2))
                        + amplitude*np.exp(-radius2/(2*8.**2)))
    if slope:
        pixels += .8*xx - 1.1*yy
    return pixels


def reference_crossing(amplitude, level):
    # Continuous analytic Fourier transform of the complete 2D PSF. No
    # production background, support, FFT or interpolation helper is reused.
    def response(f):
        return ((1.5**2*math.exp(-2*math.pi**2*(.15*f)**2)
                 + amplitude*8**2*math.exp(-2*math.pi**2*(.8*f)**2))
                / (1.5**2+amplitude*8**2))
    lo, hi = 0., 5.
    for _ in range(70):
        mid = (lo+hi)/2
        if response(mid) > level:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


@pytest.mark.parametrize('amplitude', [.005, .01, .02, .04, -.01, -.02])
@pytest.mark.parametrize('slope', [False, True])
def test_weak_wide_response_is_not_subtracted_or_truncated(amplitude, slope):
    result = compute_point_source_mtf(wide_source(amplitude, slope=slope), .1, .1,
                                      analysis_method='tukey_fft')
    for axis in (result.x, result.y):
        assert axis.mtf50 == pytest.approx(reference_crossing(amplitude, .5), rel=.01)
        assert axis.mtf10 == pytest.approx(reference_crossing(amplitude, .1), rel=.01)
        if amplitude < 0:
            assert min(axis.lsf) < 0


def test_small_selection_extends_to_include_wide_response_without_changing_target():
    image = wide_source(.02)
    result = compute_mtf_with_context(image[121:136, 121:136], .1, .1,
                                      context=(image, (121, 121)))
    assert result.x.mtf50 == pytest.approx(reference_crossing(.02, .5), rel=.01)
    assert result.y.mtf10 == pytest.approx(reference_crossing(.02, .1), rel=.01)


def test_wide_response_requires_more_than_the_old_background_ring():
    image = wide_source(.02)
    with pytest.raises(ValueError, match='背景不足'):
        compute_point_source_mtf(image[104:153, 104:153], .1, .1, analysis_method='tukey_fft')


def test_wide_response_is_stable_under_subpixel_phase_and_slope():
    for phase in (0., .2, .5, .8):
        result = compute_point_source_mtf(wide_source(.02, slope=True,
                   center=(128+phase, 128-phase)), .1, .1, analysis_method='tukey_fft')
        assert result.x.mtf50 == pytest.approx(reference_crossing(.02, .5), rel=.01)
        assert result.y.mtf10 == pytest.approx(reference_crossing(.02, .1), rel=.01)


def test_sampling_geometry_survives_context_expansion_and_workspace_roundtrip():
    from voxplane.core.workspace_state import encode, decode
    image = wide_source(.02)
    result = compute_mtf_with_context(image[121:136, 121:136], .1, .1,
                                      context=(image, (121, 121)))
    sampling = getattr(result, 'sampling', None)
    assert sampling is not None
    assert sampling.center == (7., 7.)  # Original selected ROI, not expanded buffer.
    assert sampling.half_size[0] > 25
    assert sampling.background_half_size[0] > sampling.half_size[0]
    assert decode(encode(result)) == result
    old = encode(result)
    old['fields'].pop('sampling')
    restored = decode(old)
    assert restored.sampling is None
    assert restored.x == result.x and restored.y == result.y


def test_anisotropic_wide_tail_is_retained():
    yy, xx = np.mgrid[-128:129, -128:129]
    pixels = 100+2000*(np.exp(-(xx**2+yy**2)/(2*1.5**2))
                       + .04*np.exp(-.5*((xx/8.)**2+(yy/2.)**2)))
    result = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    for axis, sigma in ((result.x, .8), (result.y, .2)):
        def analytic(f):
            return ((2.25*np.exp(-2*np.pi**2*(.15*f)**2)
                     + .64*np.exp(-2*np.pi**2*(sigma*f)**2))/2.89)
        np.testing.assert_allclose(axis.mtf, analytic(np.array(axis.frequency)), atol=.005)


@pytest.mark.parametrize('noise', [1., 2.])
def test_low_noise_does_not_hide_wide_tail_at_the_taper_boundary(noise):
    # Core amplitude 2000; independent Gaussian noise 0.05--0.1% of it.
    # Check multiple realizations rather than tune to one lucky noise pattern.
    values = []
    for seed in range(12):
        pixels = wide_source(.02)+np.random.default_rng(seed).normal(0, noise, (257, 257))
        result = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
        values.extend([result.x.mtf50, result.y.mtf50])
    assert np.median(values) == pytest.approx(reference_crossing(.02, .5), rel=.02)


def test_oblique_wide_tail_is_not_mistaken_for_an_isolated_neighbor():
    yy, xx = np.mgrid[-128:129, -128:129]
    along, across = (xx+yy)/np.sqrt(2), (yy-xx)/np.sqrt(2)
    pixels = 100+2000*(np.exp(-(xx**2+yy**2)/(2*1.5**2))
                       + .04*np.exp(-.5*((along/8.)**2+(across/2.)**2)))
    result = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    for axis in (result.x, result.y):
        frequency = np.array(axis.frequency)
        expected = (2.25*np.exp(-2*np.pi**2*(.15*frequency)**2)
                    + .64*np.exp(-2*np.pi**2*.34*frequency**2))/2.89
        np.testing.assert_allclose(axis.mtf, expected, atol=.005)


@pytest.mark.parametrize('major,size', [(16., 257), (32., 513)])
def test_narrow_diagonal_tail_in_opposed_sectors_is_retained(major, size):
    yy, xx = np.mgrid[:size, :size]
    xx, yy = xx-size//2, yy-size//2
    along, across = (xx+yy)/np.sqrt(2), (yy-xx)/np.sqrt(2)
    pixels = 100+2000*(np.exp(-(xx**2+yy**2)/4.5)
                       + .04*np.exp(-.5*((along/major)**2+(across/1.5)**2)))
    result = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    tail_mass = .04*major*1.5
    variance = .01*(major**2+1.5**2)/2
    for axis in (result.x, result.y):
        frequency = np.array(axis.frequency)
        expected = (2.25*np.exp(-2*np.pi**2*.15**2*frequency**2)
                    + tail_mass*np.exp(-2*np.pi**2*variance*frequency**2))/(2.25+tail_mass)
        np.testing.assert_allclose(axis.mtf, expected, atol=.005)


@pytest.mark.parametrize('changes', [
    {'center': (-1., 2.)}, {'half_size': (0., 3.)},
    {'background_half_size': (1., 1.)}, {'half_size': (float('inf'), 3.)},
])
def test_invalid_saved_sampling_bounds_are_rejected(changes):
    from dataclasses import replace
    from voxplane.core.workspace_state import encode, decode
    result = compute_point_source_mtf(wide_source(.02), .1, .1, analysis_method='tukey_fft')
    with pytest.raises(ValueError):
        decode(encode(replace(result, sampling=replace(result.sampling, **changes))))


@pytest.mark.parametrize('amplitude', [2000., 5000.])
def test_expansion_reports_nearby_strong_source_without_switching_targets(amplitude):
    image = wide_source(.02)
    image[128, 153] += amplitude
    result = compute_mtf_with_context(image[121:136, 121:136], .1, .1,
                                      context=(image, (121, 121)))
    assert result.sampling.center == (7., 7.)
    assert any('额外强峰' in str(w) for w in result.warnings)
    # Retain the measured spectrum and values, but do not silently report a
    # clean isolated-point measurement after sampling a neighboring source.
    assert result.x.mtf50 is not None and result.y.mtf50 is not None
