"""Expanded MTF scenarios with complete, independently known source responses."""
import numpy as np
import pytest

from qt_dicom_viewer.core.bead_mtf import compute_mtf_with_context, compute_point_source_mtf


def gaussian_source(size=257, *, center=None):
    y, x = np.mgrid[:size, :size]
    cx, cy = center or (size//2, size//2)
    x, y = x-cx, y-cy
    return x, y, np.exp(-(x*x+y*y)/4.5)


def assert_complete_spectrum(result, psf, spacing, tolerance=.005):
    """Use a direct complex-exponential sum of the *complete* known PSF.

    This oracle has no estimated background, adaptive support or production
    FFT/window helpers. Compare full curves and independently bisected first
    downward crossings, including cases with asymmetric phase.
    """
    for axis, lsf, step in ((result.x, psf.sum(axis=0), spacing[1]),
                            (result.y, psf.sum(axis=1), spacing[0])):
        position = np.arange(len(lsf))*step
        def response(f):
            return abs(np.exp(-2j*np.pi*np.asarray(f)[..., None]*position) @ lsf)/lsf.sum()
        frequencies = np.asarray(axis.frequency)
        # Sample the entire frequency domain, without allocating an enormous
        # frequency-by-pixel matrix for the longest synthetic sources.
        indices = np.unique(np.r_[np.arange(0, len(frequencies), max(1, len(frequencies)//300)),
                                  len(frequencies)-1])
        np.testing.assert_allclose(np.asarray(axis.mtf)[indices], response(frequencies[indices]),
                                   atol=tolerance, rtol=0)
        grid = np.linspace(0, .5/step, 1001)
        values = response(grid)
        for level, actual in ((.5, axis.mtf50), (.1, axis.mtf10)):
            crossings = np.flatnonzero((values[:-1] > level) & (values[1:] <= level))
            if not len(crossings):
                assert actual is None
                continue
            lo, hi = grid[crossings[0]:crossings[0]+2]
            for _ in range(45):
                mid = (lo+hi)/2
                if response(mid) > level:
                    lo = mid
                else:
                    hi = mid
            assert actual == pytest.approx((lo+hi)/2, rel=.01)


@pytest.mark.parametrize('angle', [0, 20, 45, 70, 90])
@pytest.mark.parametrize('spacing', [(.1, .1), (.23, .09)])
def test_rotated_thin_tail_with_anisotropic_physical_pixels(angle, spacing):
    x, y, core = gaussian_source()
    theta = np.deg2rad(angle)
    along = x*np.cos(theta)+y*np.sin(theta)
    across = -x*np.sin(theta)+y*np.cos(theta)
    psf = core+.04*np.exp(-.5*((along/16)**2+(across/1.5)**2))
    result = compute_point_source_mtf(2000*psf+100+.3*x-.7*y, *spacing,
                                      analysis_method='tukey_fft')
    assert_complete_spectrum(result, psf, spacing)


def asymmetric_source(direction, tail_mass=.5):
    x, y, core = gaussian_source(513)
    position = x[0]
    profile = np.exp(-position**2/4.5)
    kernel = np.exp(-np.arange(257)/12.)
    kernel /= kernel.sum()
    tail = np.convolve(profile, kernel)[:len(profile)]
    psf = core+tail_mass*np.outer(np.exp(-position**2/4.5), tail)
    if direction == 'left':
        psf = psf[:, ::-1]
    elif direction == 'down':
        psf = psf.T
    elif direction == 'up':
        psf = psf.T[::-1]
    return psf


@pytest.mark.parametrize('direction', ['right', 'left', 'down', 'up'])
@pytest.mark.parametrize('tail_mass', [.5, -.25])
def test_connected_one_sided_tail_is_not_discarded_as_background(direction, tail_mass):
    psf = asymmetric_source(direction, tail_mass)
    result = compute_point_source_mtf(100+2000*psf, .1, .1, analysis_method='tukey_fft')
    assert_complete_spectrum(result, psf, (.1, .1))


@pytest.mark.parametrize('direction', ['right', 'left', 'down', 'up'])
@pytest.mark.parametrize('tail_mass', [.5, -.25])
def test_one_sided_tail_expands_only_the_axis_that_needs_more_pixels(direction, tail_mass):
    psf = asymmetric_source(direction, tail_mass)
    horizontal = direction in ('left', 'right')
    # The short axis already contains the full Gaussian plus clean background.
    # It must not demand the large margin needed by the other axis's tail.
    psf = psf[232:281, :] if horizontal else psf[:, 232:281]
    image = 100+2000*psf
    cy, cx = np.asarray(image.shape)//2
    result = compute_mtf_with_context(image[cy-7:cy+8, cx-7:cx+8], .1, .1,
                                      context=(image, (cy-7, cx-7)))
    assert result.sampling.center == (7., 7.)
    assert result.sampling.background_half_size[1 if horizontal else 0] < 24
    assert_complete_spectrum(result, psf, (.1, .1))


@pytest.mark.parametrize('angle', [25, 45, 135])
def test_oblique_one_sided_trail_preserves_phase_in_projected_spectrum(angle):
    x, y, core = gaussian_source(513)
    theta = np.deg2rad(angle)
    trail = np.zeros_like(core)
    for distance in range(200):
        shifted = np.exp(-((x-distance*np.cos(theta))**2
                           +(y-distance*np.sin(theta))**2)/4.5)
        trail += (1-np.exp(-1/12))*np.exp(-distance/12)*shifted
    psf = core+.5*trail
    result = compute_point_source_mtf(100+2000*psf+.2*x-.3*y, .12, .08,
                                      analysis_method='tukey_fft')
    assert_complete_spectrum(result, psf, (.12, .08))


@pytest.mark.parametrize('amplitude', [200., 2000.])
@pytest.mark.parametrize('dtype,offset', [(np.int16, -1000), (np.uint16, 1200)])
def test_integer_storage_quantization_does_not_create_a_false_background_tail(amplitude, dtype, offset):
    x, y, core = gaussian_source()
    psf = core+.02*np.exp(-(x*x+y*y)/128)
    pixels = np.rint(offset+amplitude*psf).astype(dtype)
    result = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    # Use the actual quantized response as the known sampled signal, not the
    # pre-quantization Gaussian that no longer exists in the stored image.
    assert_complete_spectrum(result, pixels.astype(float)-offset, (.1, .1))


@pytest.mark.parametrize('neighbor', ['pixel', 'compact-blob'])
def test_separated_structure_does_not_drive_unilateral_expansion(neighbor):
    x, y, core = gaussian_source()
    image = 100+2000*core
    if neighbor == 'pixel':
        image[128, 144] += 2000
    else:
        image += 1800*np.exp(-((x-18)**2+y*y)/2)
    result = compute_mtf_with_context(image[121:136, 121:136], .1, .1,
                                      context=(image, (121, 121)))
    assert result.sampling.center == (7., 7.)
    assert result.sampling.half_size[0] < 16
    assert_complete_spectrum(result, core, (.1, .1))


@pytest.mark.parametrize('gain,offset,dtype', [(1., 0., np.float64), (.01, -1000., np.float64),
                                           (100., 1e6, np.float64), (1., -1000., np.float32)])
def test_adaptive_tail_is_invariant_to_rescale_and_pixel_storage(gain, offset, dtype):
    x, y, core = gaussian_source()
    psf = core+.02*np.exp(-(x*x+y*y)/128)
    pixels = (gain*(2000*psf+.4*x-.2*y)+offset).astype(dtype)
    result = compute_point_source_mtf(pixels, .17, .11, analysis_method='tukey_fft')
    assert_complete_spectrum(result, psf, (.17, .11))


@pytest.mark.parametrize('edge', ['left', 'right', 'top', 'bottom'])
def test_context_at_each_image_edge_rejects_missing_wide_tail(edge):
    centers = {'left': (18, 128), 'right': (238, 128),
               'top': (128, 18), 'bottom': (128, 238)}
    cx, cy = centers[edge]
    x, y, core = gaussian_source(center=(cx, cy))
    image = 100+2000*(core+.02*np.exp(-(x*x+y*y)/128))
    roi = image[cy-7:cy+8, cx-7:cx+8]
    with pytest.raises(ValueError, match='边缘'):
        compute_mtf_with_context(roi, .1, .1, context=(image, (cy-7, cx-7)))


@pytest.mark.parametrize('origin', [(140, 160), (220, 240), (300, 340)])
def test_translated_non_square_context_keeps_original_target_coordinates(origin):
    # Non-square image and different row/column origins catch coordinate swaps.
    cy, cx = np.asarray(origin)+(10, 13)
    y, x = np.mgrid[:511, :557]
    r2 = (x-cx)**2+(y-cy)**2
    psf = np.exp(-r2/4.5)+.02*np.exp(-r2/128)
    image = 100+2000*psf
    row, col = origin
    result = compute_mtf_with_context(image[row:row+21, col:col+27], .12, .08,
                                      context=(image, origin))
    assert result.sampling.center == (13., 10.)
    assert_complete_spectrum(result, psf, (.12, .08))
