"""Production uses one 110% calculation; comparisons are explicit audit work."""
from dataclasses import replace

import numpy as np
import pytest

from voxplane.core import bead_mtf as mtf


def source():
    y, x = np.mgrid[-48:49, -48:49]
    return 80+2000*np.exp(-.5*((x/1.6)**2+(y/1.8)**2))


def test_default_does_not_run_comparison_background_or_store_comparisons(monkeypatch):
    support = mtf._source_support
    calls = []
    def measured_support(*args, **kwargs):
        calls.append(kwargs.get('background_extent', 6.))
        return support(*args, **kwargs)
    monkeypatch.setattr(mtf, '_source_support', measured_support)
    result = mtf.compute_point_source_mtf(source(), .15, .1, analysis_method='tukey_fft')
    assert calls == [6.]
    assert result.x.sensitivity == result.y.sensitivity == ()
    assert result.sensitivity_threshold is None
    assert result.integration_scale == 1.1


@pytest.mark.parametrize('method', ['tukey_fft', 'gaussian'])
def test_context_and_fallback_only_compute_comparisons_when_requested(method):
    x = np.arange(129)-64
    g = (2-(x/2)**2)*np.exp(-.5*(x/2)**2)
    image = 80+1000*np.outer(g, g)
    roi = image[56:73, 52:77]  # 17 × 25 rectangle; needs external background.
    normal = mtf.compute_mtf_with_context(roi, .1, .1, context=(image, (56, 52)), analysis_method=method)
    audit = mtf.compute_mtf_with_context(roi, .1, .1, context=(image, (56, 52)),
                                        analysis_method=method, check_stability=True)
    assert normal.x.sensitivity == normal.y.sensitivity == ()
    assert normal.sensitivity_threshold is None
    assert normal.analysis_method == audit.analysis_method == 'tukey_fft'
    assert normal.sampling == audit.sampling
    assert normal.sampling.center == (12., 8.)
    for a, b in ((normal.x, audit.x), (normal.y, audit.y)):
        assert len(b.sensitivity) == 3
        assert a == replace(b, sensitivity=())  # Entire curve and all metrics.


@pytest.mark.parametrize('bounds', [(40, 57, 34, 63), (33, 64, 39, 58), (20, 78, 24, 73)])
def test_rectangular_selection_locates_same_target_without_square_center_crop(bounds):
    image = source()
    r0, r1, c0, c1 = bounds
    result = mtf.compute_mtf_with_context(image[r0:r1, c0:c1], .15, .1,
                                         context=(image, (r0, c0)))
    reference = mtf.compute_mtf_with_context(image, .15, .1)
    assert result.sampling.center == (48-c0, 48-r0)
    assert result.x.mtf50 == pytest.approx(reference.x.mtf50, rel=1e-6)
    assert result.y.mtf10 == pytest.approx(reference.y.mtf10, rel=1e-6)
