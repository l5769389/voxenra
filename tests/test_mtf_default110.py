"""The new default is the previously reported 110%, not 110% of 110%."""
from dataclasses import replace

import numpy as np
import pytest

from voxplane.core.bead_mtf import compute_point_source_mtf, compute_mtf_with_context
from voxplane.core.workspace_state import encode, decode
from voxplane.core.mtf_quality import sensitivity_details


def noisy_source(slope=False):
    y, x = np.mgrid[-32:33, -32:33]
    pixels = (80+1000*np.exp(-.5*((x/1.6)**2+(y/1.8)**2))
              +135*np.random.default_rng(7).normal(size=(65, 65)))
    return pixels+.7*x-1.3*y if slope else pixels


@pytest.mark.parametrize('slope', [False, True])
def test_default_matches_previous_110_without_changing_background(slope):
    result = compute_point_source_mtf(noisy_source(slope), .1953, .15, analysis_method='tukey_fft', check_stability=True)
    # Captured from the preceding calculator's window110 before this change.
    np.testing.assert_allclose([result.x.mtf50, result.x.mtf10, result.y.mtf50, result.y.mtf10],
        [.47267795515820465, 1.3443440911968498, .43661878339488147, .8470843270102634], rtol=1e-12)
    assert result.background == pytest.approx(78.80415542855235, abs=1e-10)
    assert result.noise == pytest.approx(136.50602264652278, abs=1e-10)
    for axis, baseline in ((result.x, 1.6826781708455987), (result.y, .8549391980865867)):
        assert [s.variant for s in axis.sensitivity] == ['window90', 'window100', 'background55']
        assert axis.sensitivity[1].mtf10 == pytest.approx(baseline, rel=1e-12)
    assert result.integration_scale == 1.1
    details = sensitivity_details(result, 'lp/cm')
    assert '默认计算（110%）' in details and '加权范围 100%' in details


def test_geometry_and_history_distinguish_background_from_integration():
    result = compute_point_source_mtf(noisy_source(), .1953, .15, analysis_method='tukey_fft', check_stability=True)
    s = result.sampling
    np.testing.assert_allclose(s.half_size, np.array(s.background_inner_half_size)*1.1)
    np.testing.assert_allclose(s.background_half_size, np.array(s.background_inner_half_size)*1.5)
    assert decode(encode(result)) == result
    old = encode(result)
    old['fields'].pop('integration_scale')
    old['fields']['sampling']['fields'].pop('background_inner_half_size')
    restored = decode(old)
    assert restored.integration_scale == 1.
    assert restored.sampling.background_inner_half_size is None
    assert restored.x == result.x
    assert '默认计算（100%）' in sensitivity_details(restored, 'lp/cm')


@pytest.mark.parametrize('bad', [0., -1., float('nan'), float('inf'), True])
def test_invalid_saved_integration_scale_is_rejected(bad):
    result = compute_point_source_mtf(noisy_source(), .1953, .15, analysis_method='tukey_fft', check_stability=True)
    with pytest.raises(ValueError):
        decode(encode(replace(result, integration_scale=bad)))


@pytest.mark.parametrize('bad', [(0., 2.), (1e8, 2.), (float('nan'), 2.), (2.,)])
def test_invalid_saved_background_inner_boundary_is_rejected(bad):
    result = compute_point_source_mtf(noisy_source(), .1953, .15, analysis_method='tukey_fft', check_stability=True)
    with pytest.raises(ValueError):
        decode(encode(replace(result, sampling=replace(result.sampling, background_inner_half_size=bad))))


@pytest.mark.parametrize('size', [17, 25, 33, 49])
def test_gaussian_fallback_can_extend_background_from_real_context(size):
    x = np.arange(129)-64
    g = (2-(x/2)**2)*np.exp(-.5*(x/2)**2)
    image = 80+1000*np.outer(g, g)
    low, high = 64-size//2, 65+size//2
    roi = image[low:high, low:high]
    result = compute_mtf_with_context(roi, .1, .1, context=(image, (low, low)), analysis_method='gaussian')
    reference = compute_mtf_with_context(roi, .1, .1, context=(image, (low, low)))
    assert result.analysis_method == 'tukey_fft'
    assert result.x == reference.x and result.y == reference.y
    assert result.sampling.center == (size//2, size//2)
    assert result.integration_scale == 1.1
    assert any('自动改用' in str(w) for w in result.warnings)
