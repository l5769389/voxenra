from dataclasses import replace
import math

import numpy as np
import pytest

from qt_dicom_viewer.core import bead_mtf as mtf
from qt_dicom_viewer.core.workspace_state import encode, decode
from test_bead_mtf import gaussian


def noisy_source():
    yy, xx = np.mgrid[-32:33, -32:33]
    return (80 + 1000*np.exp(-.5*((xx/1.6)**2 + (yy/1.8)**2))
            + 135*np.random.default_rng(7).normal(size=(65, 65)))


def test_sensitive_metric_keeps_default_crossing_and_curve():
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    assert result.x.mtf10 is not None
    assert np.interp(result.x.mtf10, result.x.frequency, result.x.mtf) == pytest.approx(.1)
    assert not result.x.unreliable_metrics
    assert len(result.x.sensitivity) == 3
    assert max(abs(s.mtf10 / result.x.mtf10 - 1) for s in result.x.sensitivity) > .2
    assert result.sensitivity_threshold == .2


def test_comparison_failure_retains_baseline_and_successful_comparisons(monkeypatch):
    original = mtf._source_support
    def support(*args, **kwargs):
        if kwargs.get('background_extent') == 5.5:
            raise ValueError('background comparison unavailable')
        return original(*args, **kwargs)
    monkeypatch.setattr(mtf, '_source_support', support)
    result = mtf.compute_point_source_mtf(gaussian(sigma_x=.2, sigma_y=.2), .15, .1, analysis_method='tukey_fft')
    for axis in (result.x, result.y):
        assert axis.mtf50 is not None and axis.mtf10 is not None
        assert not axis.unreliable_metrics
        assert [bool(s.error) for s in axis.sensitivity] == [False, False, True]


def test_failed_x_comparison_does_not_drop_y_comparison(monkeypatch):
    original = mtf._axis_result
    calls = 0
    def axis(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:  # X for the first comparison, after both baseline axes.
            raise ValueError('X comparison failed')
        return original(*args, **kwargs)
    monkeypatch.setattr(mtf, '_axis_result', axis)
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    assert result.x.sensitivity[0].error
    assert result.y.sensitivity[0].mtf50 is not None
    assert not result.y.sensitivity[0].error
    assert result.x.mtf50 is not None


def test_warning_threshold_never_changes_calculated_values():
    results = [mtf.compute_point_source_mtf(noisy_source(), .1953, .1953,
               analysis_method='tukey_fft', sensitivity_threshold=t) for t in (.1, .2, .5)]
    assert results[0].x == results[1].x == results[2].x
    assert results[0].y == results[1].y == results[2].y
    assert [r.sensitivity_threshold for r in results] == [.1, .2, .5]


def test_equivalent_inherits_anchor_sensitivity_not_measured_mtf50():
    from qt_dicom_viewer.model.mtf import MtfSensitivitySample
    base = mtf.compute_point_source_mtf(gaussian(sigma_x=.2, sigma_y=.2), .15, .1, analysis_method='tukey_fft')
    axis = replace(base.x, mtf50=1., mtf10=2., sensitivity=(
        MtfSensitivitySample('window90', .1, 2.1),
        MtfSensitivitySample('window110', 1.1, 2.8)))
    result = mtf.gaussian_equivalent_from_mtf10(replace(base, x=axis))
    assert result.x.mtf10 == 2.
    assert result.x.mtf50 == pytest.approx(2*math.sqrt(math.log(2)/math.log(10)))
    assert result.x.sensitivity[0].mtf50 == pytest.approx(2.1*math.sqrt(math.log(2)/math.log(10)))
    assert result.x.sensitivity[1].mtf10 == 2.8


def test_new_and_legacy_results_roundtrip_without_inventing_missing_values():
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    assert decode(encode(result)) == result
    old = encode(replace(result, x=replace(result.x, mtf10=None, unreliable_metrics=('mtf10',))))
    for key in ('notes', 'sensitivity_threshold'):
        old['fields'].pop(key, None)
    for axis in ('x', 'y'):
        old['fields'][axis]['fields'].pop('sensitivity', None)
    restored = decode(old)
    assert restored.x.mtf10 is None and restored.x.unreliable_metrics == ('mtf10',)
    assert restored.x.sensitivity == () and restored.sensitivity_threshold is None


def test_missing_baseline_crossing_stays_missing():
    pixels = np.zeros((33, 33)); pixels[16, 16] = 10
    result = mtf.compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    assert result.x.mtf50 is None and result.x.mtf10 is None


def test_new_missing_anchor_is_not_reported_as_legacy_withheld():
    from qt_dicom_viewer.core.mtf_quality import quality_warnings
    pixels = np.zeros((33, 33)); pixels[16, 16] = 10
    measured = mtf.compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    result = mtf.gaussian_equivalent_from_mtf10(measured)
    assert not any('旧版' in str(w) or '重新计算' in str(w) for w in quality_warnings(result))
    assert result.x.mtf50 is None and result.x.mtf == ()


def test_metric_diagnostics_show_percent_and_preserve_comparison_units():
    from qt_dicom_viewer.core.mtf_quality import metric_quality, sensitivity_details
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    quality = metric_quality(result.x, 'mtf10', result.sensitivity_threshold, 'X')
    assert quality['status'] == 'sensitive'
    assert quality['relativeChange'] == pytest.approx(.20107, abs=.00001)
    assert '20.1%' in quality['message']
    assert metric_quality(result.x, 'mtf10', .5, 'X')['status'] == 'ok'
    details = sensitivity_details(result, 'lp/cm')
    assert '20%' in details and 'lp/cm' in details
    assert f'{result.x.sensitivity[0].mtf10*10:.3f}' in details


def test_incomplete_and_no_crossing_comparisons_are_distinct():
    from qt_dicom_viewer.core.mtf_quality import metric_quality
    from qt_dicom_viewer.model.mtf import MtfSensitivitySample
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    failed = replace(result.x, sensitivity=(MtfSensitivitySample('window90', None, None, 'error'),))
    missing = replace(result.x, sensitivity=(MtfSensitivitySample('window90', None, None),))
    assert metric_quality(failed, 'mtf10', .2, 'X')['status'] == 'incomplete'
    assert metric_quality(missing, 'mtf10', .2, 'X')['status'] == 'missing-crossing'


def test_sensitivity_setting_is_bounded_and_persistent(tmp_path):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    path = tmp_path / 'settings.json'
    settings = SettingsController(path=path)
    assert settings.section('services')['mtfSensitivityPercent'] == 20
    assert settings.setValue('services', 'mtfSensitivityPercent', 35)
    assert SettingsController(path=path).section('services')['mtfSensitivityPercent'] == 35
    for bad in (0, -1, 101, float('nan'), float('inf'), True, '30'):
        assert not settings.setValue('services', 'mtfSensitivityPercent', bad)


def test_unknown_saved_comparison_name_has_safe_text_fallback():
    from qt_dicom_viewer.core.mtf_quality import sensitivity_details
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    axis = replace(result.x, sensitivity=(replace(result.x.sensitivity[0], variant='future-comparison'),))
    restored = decode(encode(replace(result, x=axis)))
    assert 'future-comparison' in sensitivity_details(restored, 'lp/mm')


@pytest.mark.parametrize('threshold', [-.2, 0., 99.])
def test_workspace_rejects_out_of_range_sensitivity_threshold(threshold):
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    with pytest.raises(ValueError):
        decode(encode(replace(result, sensitivity_threshold=threshold)))


@pytest.mark.parametrize('bad_sample', ['negative', 'duplicate', 'no-name'])
def test_workspace_rejects_invalid_comparison_metadata(bad_sample):
    result = mtf.compute_point_source_mtf(noisy_source(), .1953, .1953, analysis_method='tukey_fft')
    samples = result.x.sensitivity
    if bad_sample == 'negative':
        samples = (replace(samples[0], mtf10=-1.),)
    elif bad_sample == 'duplicate':
        samples = (samples[0], samples[0])
    else:
        samples = (replace(samples[0], variant=''),)
    with pytest.raises(ValueError):
        decode(encode(replace(result, x=replace(result.x, sensitivity=samples))))
