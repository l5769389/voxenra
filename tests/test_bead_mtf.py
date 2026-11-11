"""解析高斯作为独立基准，不用另一遍 FFT 生成测试期望。"""

import math

import numpy as np
import pytest

from voxplane.core.bead_mtf import (
    compute_point_source_mtf, extract_rect_pixels, lsf_fwhm,
    threshold_frequency, edge_taper, has_negative_sidelobes,
    subtract_lsf_baseline, _axis_result,
)
from voxplane.model import ImagePoint


def gaussian(rows=128, columns=128, row_spacing=.15, column_spacing=.1,
             sigma_x=.8, sigma_y=1.2):
    x = (np.arange(columns) - (columns - 1) / 2) * column_spacing
    y = (np.arange(rows) - (rows - 1) / 2) * row_spacing
    return 80 + 1000 * np.exp(-.5 * ((x[None, :] / sigma_x) ** 2
                                    + (y[:, None] / sigma_y) ** 2))


@pytest.mark.parametrize("analysis_method", ["direct_fft", "tukey_fft"])
@pytest.mark.parametrize("spacing,sigmas", [((.15, .1), (.8, 1.2)), ((.12, .2), (1.2, .8))])
def test_anisotropic_gaussian_matches_analytic_curves_and_metrics(spacing, sigmas, analysis_method):
    pixels = gaussian(rows=256, columns=256, row_spacing=spacing[0], column_spacing=spacing[1],
                      sigma_x=sigmas[0], sigma_y=sigmas[1])
    original = pixels.copy()
    result = compute_point_source_mtf(pixels, *spacing, analysis_method=analysis_method)
    for axis, sigma, delta in [(result.x, sigmas[0], spacing[1]), (result.y, sigmas[1], spacing[0])]:
        expected_curve = np.exp(-2 * math.pi ** 2 * sigma ** 2 * np.array(axis.frequency) ** 2)
        np.testing.assert_allclose(axis.mtf, expected_curve, atol=2e-6)
        assert axis.frequency[-1] == pytest.approx(.5 / delta)
        assert axis.mtf50 == pytest.approx(math.sqrt(-math.log(.5) / (2 * math.pi ** 2 * sigma ** 2)), rel=.002)
        assert axis.mtf10 == pytest.approx(math.sqrt(-math.log(.1) / (2 * math.pi ** 2 * sigma ** 2)), rel=.004)
        assert axis.fwhm == pytest.approx(2 * math.sqrt(2 * math.log(2)) * sigma, rel=.006)
    assert not result.warnings
    np.testing.assert_array_equal(pixels, original)


def test_gaussian_analysis_fits_lsf_and_reports_analytic_equivalent_metrics():
    sigma_x, sigma_y = .8, 1.2
    result = compute_point_source_mtf(
        gaussian(sigma_x=sigma_x, sigma_y=sigma_y),
        .15,
        .1,
        measurement_method="bead",
        analysis_method="gaussian",
    )
    for axis, sigma in ((result.x, sigma_x), (result.y, sigma_y)):
        assert axis.fwhm == pytest.approx(2 * math.sqrt(2 * math.log(2)) * sigma, rel=.003)
        assert axis.mtf50 == pytest.approx(
            math.sqrt(math.log(2)) / (math.sqrt(2) * math.pi * sigma), rel=.003
        )
        assert axis.mtf10 == pytest.approx(
            math.sqrt(math.log(10)) / (math.sqrt(2) * math.pi * sigma), rel=.003
        )
        assert max(axis.mtf) == pytest.approx(1)
    assert not result.warnings


def test_wire_cross_section_uses_same_point_source_pipeline_without_size_correction():
    pixels = gaussian()
    bead = compute_point_source_mtf(pixels, .15, .1, measurement_method="bead")
    wire = compute_point_source_mtf(pixels, .15, .1, measurement_method="wire")
    np.testing.assert_allclose(wire.x.mtf, bead.x.mtf)
    np.testing.assert_allclose(wire.y.mtf, bead.y.mtf)


@pytest.mark.parametrize("keywords", [
    {"measurement_method": "edge"},
    {"analysis_method": "unknown"},
])
def test_unknown_method_or_analysis_is_rejected(keywords):
    with pytest.raises(ValueError, match="不支持"):
        compute_point_source_mtf(gaussian(), .15, .1, **keywords)


def test_background_offset_and_positive_scaling_do_not_change_mtf():
    pixels = gaussian()
    first = compute_point_source_mtf(pixels, .15, .1)
    second = compute_point_source_mtf(pixels * 2.3 - 1200, .15, .1)
    for a, b in [(first.x, second.x), (first.y, second.y)]:
        np.testing.assert_allclose(a.mtf, b.mtf, atol=1e-13)
        assert a.fwhm == pytest.approx(b.fwhm)


def test_negative_lobes_are_retained_and_response_can_exceed_one():
    pixels = np.zeros((24, 24))
    pixels[12, 12] = 10
    pixels[12, 11] = pixels[12, 13] = -2
    result = compute_point_source_mtf(pixels, .5, .25)
    assert min(result.x.lsf) < 0
    assert max(result.x.mtf) > 2
    assert result.x.mtf50 is None and result.x.mtf10 is None
    assert result.x.lsf[12] == 5
    assert result.y.lsf[12] == 1.5


def test_threshold_uses_first_downward_crossing_and_warns_repeated_crossings():
    f = np.arange(7, dtype=float)
    response = np.array([1, .6, .4, .8, .5, .3, .1])
    crossing, multiple = threshold_frequency(f, response, .5)
    assert crossing == 1.5
    assert multiple
    assert threshold_frequency(f, response, .05) == (None, False)
    assert threshold_frequency(f, response, .1) == (6, False)


def test_peak_plateau_fwhm_is_not_gaussian_fitted():
    assert lsf_fwhm(np.array([0, 1, 4, 4, 1, 0]), .3) == pytest.approx(.7)
    assert lsf_fwhm(np.array([0, 1, 4, 4, 4]), .3) is None
    assert lsf_fwhm(np.zeros(8), 1) is None


def test_truncated_response_has_explicit_quality_warnings():
    pixels = np.zeros((24, 24))
    pixels[:, 0] = 10
    pixels[12, 0] = 100
    result = compute_point_source_mtf(pixels, 1, 1)
    assert any("主峰位于" in message for message in result.warnings)
    assert any("两端" in message for message in result.warnings)
    assert result.x.fwhm is None


def test_mad_low_signal_warning_is_not_a_pass_fail_decision():
    rng = np.random.default_rng(12)
    pixels = rng.normal(0, 10, (32, 32))
    pixels[8:24, 8:24] += 5
    result = compute_point_source_mtf(pixels, 1, 1)
    assert result.noise > 0
    assert any("低信号" in message for message in result.warnings)


@pytest.mark.parametrize("spacing", [(0, 1), (-1, 1), (1, float("nan")), (float("inf"), 1), (None, 1)])
def test_invalid_real_spacing_is_rejected(spacing):
    with pytest.raises(ValueError, match="间距"):
        compute_point_source_mtf(gaussian(), *spacing)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_invalid_pixels_are_not_filtered_out(value):
    pixels = gaussian()
    pixels[12, 14] = value
    with pytest.raises(ValueError, match="无效像素"):
        compute_point_source_mtf(pixels, 1, 1)


@pytest.mark.parametrize("pixels", [np.zeros((12, 12)), np.ones((12, 12)) * 1024,
                                     -np.pad(np.ones((4, 4)), 4)])
def test_flat_or_nonpositive_net_response_is_error(pixels):
    with pytest.raises(ValueError, match="有效正净响应"):
        compute_point_source_mtf(pixels, 1, 1)


def test_rect_pixel_centers_reverse_drag_and_snapshot():
    pixels = np.arange(400).reshape(20, 20)
    roi = extract_rect_pixels(pixels, [ImagePoint(12.2, 15.8), ImagePoint(2.3, 3.4)])
    np.testing.assert_array_equal(roi, pixels[4:16, 3:13])
    roi[0, 0] = -1
    assert pixels[4, 3] != -1


@pytest.mark.parametrize("points,pattern", [
    ([ImagePoint(-1, 0), ImagePoint(12, 12)], "超出"),
    ([ImagePoint(0, 0), ImagePoint(20, 12)], "超出"),
    ([ImagePoint(0, 0), ImagePoint(6.9, 12)], "8 × 8"),
    ([ImagePoint(float("nan"), 0), ImagePoint(10, 12)], "坐标"),
])
def test_crop_does_not_silently_clip_or_expand(points, pattern):
    with pytest.raises(ValueError, match=pattern):
        extract_rect_pixels(np.zeros((20, 20)), points)


def test_multiple_beads_record_crossing_rule_in_details():
    pixels = np.zeros((64, 64))
    pixels[32, 20] = pixels[32, 40] = 10
    result = compute_point_source_mtf(pixels, 1, 1)
    assert any("多次穿越" in message for message in result.notes)


def test_background_band_uses_ceil_of_ten_percent_short_side():
    pixels = np.full((19, 22), 7.0)
    pixels[:2] = pixels[-2:] = 10
    pixels[:, :2] = pixels[:, -2:] = 10
    pixels[9, 11] = 2000
    result = compute_point_source_mtf(pixels, 1, 1)
    assert result.background == 10
    assert result.noise == 0
    assert min(result.x.lsf) < 0


def test_minimum_eight_by_eight_is_allowed():
    pixels = np.zeros((8, 8))
    pixels[4, 4] = 10
    result = compute_point_source_mtf(pixels, 1, 1)
    assert len(result.x.frequency) == 513  # Dense interpolation grid; Nyquist remains unchanged.
    assert result.x.mtf10 is None


@pytest.mark.parametrize("target50", [.7, 1.13])
def test_reported_frequency_range_against_independent_gaussian_formula(target50):
    """直接覆盖本次比对量级，不能只用此前较低频率的高斯基准。"""
    sigma = math.sqrt(math.log(2)) / (math.sqrt(2) * math.pi * target50)
    pixels = gaussian(rows=64, columns=64, row_spacing=.06, column_spacing=.06,
                      sigma_x=sigma, sigma_y=sigma)
    result = compute_point_source_mtf(pixels, .06, .06)
    for axis in (result.x, result.y):
        assert axis.mtf50 == pytest.approx(target50, rel=.001)
        assert axis.mtf10 == pytest.approx(target50 * math.sqrt(math.log(10) / math.log(2)), rel=.002)


def test_discrete_binomial_response_has_analytic_thresholds_without_gaussian_assumption():
    """三点 LSF 的解析响应为 (1 + cos(2πfΔ)) / 2，验证补零、归一化及行列单位。"""
    pixels = np.zeros((16, 24))
    kernel = np.array([.25, .5, .25])
    pixels[7:10, 11:14] = kernel[:, None] * kernel[None, :]
    result = compute_point_source_mtf(pixels, .16, .11)
    for axis, spacing in [(result.x, .11), (result.y, .16)]:
        expected = .5 + .5 * np.cos(2 * math.pi * np.array(axis.frequency) * spacing)
        np.testing.assert_allclose(axis.mtf, expected, atol=1e-14)
        assert axis.mtf50 == pytest.approx(1 / (4 * spacing), abs=1e-12)
        assert axis.mtf10 == pytest.approx(math.acos(-.8) / (2 * math.pi * spacing), rel=.001)


def test_same_bead_tight_roi_contaminates_background_and_overestimates_mtf():
    """记录现有外围背景法的局限；这是合成对照，不是实际 1.13 的成因定论。"""
    sigma = math.sqrt(math.log(2)) / (math.sqrt(2) * math.pi * .7)
    pixels = gaussian(rows=64, columns=64, row_spacing=.06, column_spacing=.06,
                      sigma_x=sigma, sigma_y=sigma)
    full = compute_point_source_mtf(pixels, .06, .06)
    tight = compute_point_source_mtf(pixels[24:40, 24:40], .06, .06)
    assert full.x.mtf50 == pytest.approx(.7, rel=.001)
    assert full.x.mtf10 == pytest.approx(.7 * math.sqrt(math.log(10) / math.log(2)), rel=.002)
    assert tight.x.mtf50 > full.x.mtf50 * 1.5
    assert tight.x.mtf10 > full.x.mtf10 * 1.3
    assert full.background == pytest.approx(80, abs=.001)
    assert tight.background > 280  # 背景真值 80，但小框将微珠尾部计入外围背景。
    assert any("截断或背景偏差" in warning for warning in tight.warnings)


def test_wrong_pixel_spacing_rescales_both_thresholds_by_same_factor():
    pixels = gaussian()
    correct = compute_point_source_mtf(pixels, .15, .1)
    wrong = compute_point_source_mtf(pixels, .15 / 1.614, .1 / 1.614)
    for axis_correct, axis_wrong in [(correct.x, wrong.x), (correct.y, wrong.y)]:
        assert axis_wrong.mtf50 / axis_correct.mtf50 == pytest.approx(1.614)
        assert axis_wrong.mtf10 / axis_correct.mtf10 == pytest.approx(1.614)
        assert axis_wrong.fwhm / axis_correct.fwhm == pytest.approx(1 / 1.614)


def test_tukey_window_has_exact_flat_center_and_cosine_edges():
    expected = np.array([0, (1 - 1 / math.sqrt(2)) / 2, .5,
                         (1 + 1 / math.sqrt(2)) / 2, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, (1 + 1 / math.sqrt(2)) / 2,
                         .5, (1 - 1 / math.sqrt(2)) / 2, 0])
    np.testing.assert_allclose(edge_taper(17), expected, atol=1e-15)
    for n in (8, 9, 32, 33):
        weights = edge_taper(n)
        np.testing.assert_allclose(weights, weights[::-1], atol=1e-15)
        assert weights[0] == weights[-1] == 0
        assert weights[n // 2] == 1
        assert np.all((weights >= 0) & (weights <= 1))


def test_edge_taper_preserves_central_negative_lobes_and_original_fwhm():
    pixels = np.zeros((24, 24))
    pixels[12, 12] = 10
    pixels[12, 11] = pixels[12, 13] = -2
    direct = compute_point_source_mtf(pixels, .5, .25)
    weighted_x = _axis_result(np.array(direct.x.lsf), .25, 'X', [], taper=True)
    weighted_y = _axis_result(np.array(direct.y.lsf), .5, 'Y', [], taper=True)
    for d, w in ((direct.x, weighted_x), (direct.y, weighted_y)):
        np.testing.assert_array_equal(w.lsf, d.lsf)
        assert w.fwhm == d.fwhm
        assert w.mtf50 == d.mtf50 and w.mtf10 == d.mtf10
        np.testing.assert_allclose(w.mtf, d.mtf, atol=1e-15)
    assert min(weighted_x.lsf) < 0


def test_edge_taper_mtf_matches_explicit_fourier_sum_and_keeps_fwhm():
    pixels = gaussian(rows=40, columns=40, row_spacing=.12, column_spacing=.2,
                      sigma_x=.3, sigma_y=.4)
    # Structured border disturbance whose weights are known, not random expectations.
    pixels[20, 1:5] += [12, -7, 6, -8]
    pixels[1:5, 20] += [6, -9, 7, 5]
    original = pixels.copy()
    direct = compute_point_source_mtf(pixels, .12, .2)
    for d, spacing in ((direct.x, .2), (direct.y, .12)):
        axis = _axis_result(np.array(d.lsf), spacing, 'axis', [], taper=True)
        lsf = np.array(d.lsf)
        # Independent piecewise cosine definition, avoiding FFT as the oracle.
        weights = [1 if .25 <= i / (len(lsf) - 1) <= .75
                   else .5 * (1 + math.cos(math.pi * (4 * i / (len(lsf) - 1) - 1)))
                   for i in range(len(lsf))]
        y = lsf * weights
        expected = [abs(sum(v * np.exp(-2j * math.pi * f * i * spacing)
                            for i, v in enumerate(y))) / sum(y) for f in axis.frequency]
        np.testing.assert_allclose(axis.mtf, expected, atol=1e-13)
        assert axis.fwhm == d.fwhm and axis.lsf == d.lsf
    np.testing.assert_array_equal(pixels, original)


def test_edge_taper_does_not_silence_original_truncation_warning():
    pixels = np.zeros((24, 24))
    pixels[12, :] = 10
    pixels[12, 12] = 100
    warnings = []
    _axis_result(pixels.sum(axis=0), 1, 'X', warnings, taper=True)
    assert any('LSF 两端' in warning for warning in warnings)
    assert any('加权区' in warning for warning in warnings)


def test_edge_taper_rejects_off_center_peak_and_nonpositive_weighted_dc():
    pixels = np.zeros((24, 24))
    pixels[12, 2] = 10
    with pytest.raises(ValueError, match='主峰偏离'):
        _axis_result(pixels.sum(axis=0), 1, 'X', [], taper=True)
    pixels = np.zeros((8, 8))
    pixels[4] = [.25, .25, -.9, 1, -.9, .25, .25, .25]
    assert pixels.sum() > 0
    with pytest.raises(ValueError, match='零频'):
        _axis_result(pixels.sum(axis=0), 1, 'X', [], taper=True)


def test_gaussian_negative_lobes_use_measured_windowed_spectrum():
    t = np.arange(64)-31.5
    lsf = np.exp(-.5*(t/2)**2)-.12*np.exp(-.5*((t-7)/2)**2)
    pixels = 80+1000*np.outer(lsf,lsf)
    result = compute_point_source_mtf(pixels,.1,.1,analysis_method='gaussian')
    measured = compute_point_source_mtf(pixels,.1,.1,analysis_method='tukey_fft')
    assert result.analysis_method == 'tukey_fft'
    assert any('自动' in w for w in result.warnings)
    for a,b in ((result.x,measured.x),(result.y,measured.y)):
        assert a == b
        assert max(a.mtf) > 1
        assert a.mtf50 != pytest.approx(a.mtf10*math.sqrt(math.log(2)/math.log(10)),rel=.01)
        for level,value in ((.5,a.mtf50),(.1,a.mtf10)):
            assert np.interp(value,a.frequency,a.mtf) == pytest.approx(level,abs=1e-12)


def test_explicit_direct_fft_remains_measured_with_negative_lobes():
    t = np.arange(64)-31.5
    lsf = np.exp(-.5*(t/2)**2)-.12*np.exp(-.5*((t-7)/2)**2)
    result = compute_point_source_mtf(80+1000*np.outer(lsf,lsf),.1,.1,analysis_method='direct_fft')
    assert result.analysis_method == 'direct_fft'
    assert max(result.x.mtf) > 1
    assert result.x == _axis_result(np.array(result.x.lsf),.1,'X',[])


@pytest.mark.parametrize("case, expected", [
    ("consecutive", True), ("isolated", False), ("distant", False),
    ("below_noise", False), ("small", False), ("gaussian", False),
])
def test_negative_sidelobe_detection_rejects_background_noise(case, expected):
    t = np.arange(65) - 32
    lsf = np.exp(-.5 * (t / 2)**2)
    if case == "isolated":
        lsf[39] = -.3
    elif case == "distant":
        lsf[53:55] = -.3
    elif case in ("consecutive", "below_noise"):
        lsf[38:40] = -.3
    elif case == "small":
        lsf[38:40] = -.04
    noise = .11 if case == "below_noise" else .01
    assert has_negative_sidelobes(lsf, noise) == expected


def test_gaussian_is_retained_for_positive_psf_and_fallback_is_measured():
    result = compute_point_source_mtf(gaussian(),.15,.1,analysis_method='gaussian')
    assert result.analysis_method == 'gaussian'
    t = np.arange(65)-32
    positive = np.exp(-.5*(t/2)**2)
    negative = positive-.18*np.exp(-.5*((t-7)/2)**2)
    pixels = 80+1000*np.outer(positive,negative)
    result = compute_point_source_mtf(pixels,.15,.1,analysis_method='gaussian')
    measured = compute_point_source_mtf(pixels,.15,.1,analysis_method='tukey_fft')
    assert result.analysis_method == 'tukey_fft'
    assert result.x == measured.x and result.y == measured.y


@pytest.mark.parametrize('enhancement', [0., .5, 1.])
def test_windowed_fft_against_analytic_sharpened_gaussian(enhancement):
    # Known impulse response and analytic transform, not an FFT-derived oracle.
    sigma,delta = .3,.025
    t = np.arange(-192,193)*delta
    lsf = (1+enhancement-enhancement*(t/sigma)**2)*np.exp(-.5*(t/sigma)**2)
    yy,xx = np.mgrid[:len(t),:len(t)]
    pixels = 80+.2*xx-.4*yy+1000*np.outer(lsf,lsf)
    result = compute_point_source_mtf(pixels,delta,delta,analysis_method='tukey_fft')
    def analytic(f):
        z = (2*np.pi*sigma*f)**2
        return (1+enhancement*z)*np.exp(-z/2)
    def crossing(level):
        lo,hi = 0.,.5/delta
        for _ in range(70):
            mid = (lo+hi)/2
            if analytic(mid)>level: lo=mid
            else: hi=mid
        return (lo+hi)/2
    for axis in (result.x,result.y):
        # The finite 3--4 FWHM taper has a bounded (<1e-5) bias on the
        # infinite analytic response, including its negative tails.
        np.testing.assert_allclose(axis.mtf,analytic(np.array(axis.frequency)),atol=1e-5)
        assert axis.mtf50 == pytest.approx(crossing(.5),rel=1e-4)
        assert axis.mtf10 == pytest.approx(crossing(.1),rel=1e-4)
        assert axis.frequency[-1] == pytest.approx(.5/delta)
    if enhancement == 1:
        assert max(result.x.mtf)>1.2
        assert result.x.mtf50 == pytest.approx(1.18087698,rel=1e-4)


def test_linear_baseline_uses_both_edge_window_centers():
    n=65
    t=np.arange(n)
    signal=100*np.exp(-.5*((t-32)/2)**2)
    corrected=subtract_lsf_baseline(signal+10+.5*t)
    np.testing.assert_allclose(corrected,signal,atol=1e-12)


def test_windowed_spectrum_matches_independent_fourier_sum():
    pixels=gaussian(rows=97,columns=97,row_spacing=.1,column_spacing=.1,sigma_x=.25,sigma_y=.3)
    pixels[30,3:6]+=[30,-10,20]
    original=pixels.copy()
    result=compute_point_source_mtf(pixels,.1,.1,analysis_method='tukey_fft')
    for axis in (result.x,result.y):
        values=np.array(axis.lsf)
        frequency=np.array(axis.frequency)
        expected=np.abs(np.exp(-2j*np.pi*frequency[:,None]*np.arange(len(values))[None,:]*.1)@values)/values.sum()
        np.testing.assert_allclose(axis.mtf,expected,atol=1e-13)
    np.testing.assert_array_equal(pixels,original)


def test_small_roi_perturbations_are_stable_for_noisy_sharp_target():
    rng=np.random.default_rng(133)
    t=np.arange(81)-40
    g=(2-(t/1.6)**2)*np.exp(-.5*(t/1.6)**2)
    yy,xx=np.mgrid[:81,:81]
    pixels=80+.3*xx-.2*yy+1500*np.outer(g,g)+rng.normal(0,2,(81,81))
    values=[]
    for size in (41,43,45,47,49):
        for dx,dy in ((-2,0),(0,-2),(0,0),(0,2),(2,0)):
            r=size//2;cx,cy=40+dx,40+dy
            result=compute_point_source_mtf(pixels[cy-r:cy+r+1,cx-r:cx+r+1],.1,.1,analysis_method='tukey_fft')
            values.append([result.x.mtf50,result.y.mtf50,result.x.mtf10,result.y.mtf10])
    values=np.array(values)
    assert np.all(np.ptp(values,axis=0)/np.median(values,axis=0)<.025)


@pytest.mark.parametrize('noise_scale, sensitive', [(50, False), (135, True)])
def test_windowed_sensitivity_marks_both_sides_of_twenty_percent(noise_scale, sensitive):
    # Fixed synthetic noise puts X MTF10 sensitivity below/above 20% with
    # the 110% baseline. Exercise the full background/window/FFT pipeline.
    yy, xx = np.mgrid[-32:33, -32:33]
    pixels = (80 + 1000*np.exp(-.5*((xx/1.6)**2 + (yy/1.8)**2))
              + noise_scale*np.random.default_rng(7).normal(size=(65, 65)))
    result = compute_point_source_mtf(pixels, .1953, .1953, analysis_method='tukey_fft', check_stability=True)
    from voxplane.core.mtf_quality import metric_quality
    assert result.x.mtf10 is not None
    assert not result.x.unreliable_metrics
    assert np.interp(result.x.mtf10, result.x.frequency, result.x.mtf) == pytest.approx(.1)
    quality = metric_quality(result.x, 'mtf10', result.sensitivity_threshold, 'X')
    assert (quality['status'] == 'sensitive') == sensitive
    assert len(result.x.mtf) > 0



def test_windowed_missing_crossings_are_not_filled_using_fwhm():
    pixels=np.zeros((33,33));pixels[16,16]=10
    result=compute_point_source_mtf(pixels,.1,.1,analysis_method='tukey_fft')
    assert result.x.fwhm is not None
    assert result.x.mtf10 is None and result.x.mtf50 is None
    np.testing.assert_allclose(result.x.mtf,1,atol=1e-14)


def test_windowed_incomplete_source_is_rejected():
    pixels=np.zeros((33,33));pixels[1,16]=10
    with pytest.raises(ValueError,match='居中'):
        compute_point_source_mtf(pixels,.1,.1,analysis_method='tukey_fft')


def test_insufficient_background_is_rejected_instead_of_truncating_support():
    full = gaussian(rows=129, columns=129, row_spacing=.1, column_spacing=.1,
                    sigma_x=.4, sigma_y=.4)
    with pytest.raises(ValueError, match='背景不足'):
        compute_point_source_mtf(full[48:81, 48:81], .1, .1, analysis_method='tukey_fft')
    large = compute_point_source_mtf(full, .1, .1, analysis_method='tukey_fft')
    assert not large.warnings
    assert large.x.mtf50 is not None and large.y.mtf10 is not None


def test_weighted_background_shift_and_signal_scaling_preserve_result():
    pixels = gaussian(rows=113, columns=113, row_spacing=.1, column_spacing=.1,
                      sigma_x=.25, sigma_y=.35)
    yy, xx = np.mgrid[:113, :113]
    original = compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
    changed = compute_point_source_mtf(pixels*7 + 200 + .3*xx - .7*yy, .1, .1,
                                       analysis_method='tukey_fft')
    for a, b in ((original.x, changed.x), (original.y, changed.y)):
        np.testing.assert_allclose(a.mtf, b.mtf, atol=1e-12)
        assert a.mtf50 == pytest.approx(b.mtf50, abs=1e-12)
        assert a.mtf10 == pytest.approx(b.mtf10, abs=1e-12)


@pytest.mark.parametrize('sample', ['helical_slice11', 'qa_slice151'])
def test_real_phantom_roi_changes_keep_support_and_metric_validity(sample):
    from pathlib import Path
    fixture = Path(__file__).parent/'fixtures/mtf/point_sources.npz'
    with np.load(fixture) as data:
        pixels = data[sample]
    measured = []
    for size in (55, 59, 63, 67):
        for dx, dy in ((0, 0), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            r = size//2
            roi = pixels[48+dy-r:49+dy+r, 48+dx-r:49+dx+r]
            result = compute_point_source_mtf(roi, .1953125, .1953125, analysis_method='tukey_fft', check_stability=True)
            assert not result.x.unreliable_metrics
            assert not result.y.unreliable_metrics
            if sample == 'qa_slice151':
                from voxplane.core.mtf_quality import metric_quality
                assert result.y.mtf50 is not None
                assert metric_quality(result.y, 'mtf50', result.sensitivity_threshold, 'Y')['status'] == 'sensitive'
            measured.append([result.x.mtf50, result.x.mtf10, result.y.mtf10])
            for axis in (result.x, result.y):
                # Reported thresholds must still lie on the displayed spectrum.
                for key, level in [('mtf50', .5), ('mtf10', .1)]:
                    value = getattr(axis, key)
                    if value is not None:
                        assert np.interp(value, axis.frequency, axis.mtf) == pytest.approx(level, abs=1e-12)
    measured = np.array(measured)
    assert np.all(np.ptp(measured, axis=0)/np.median(measured, axis=0) < .001)


def test_negative_dc_cannot_be_hidden_by_fft_magnitude():
    with pytest.raises(ValueError, match='零频'):
        _axis_result(np.array([-4., 1., -4.]), .1, 'X', [])


def test_gaussian_equivalent_uses_mtf10_and_preserves_measured_cache():
    from dataclasses import replace
    from voxplane.core.bead_mtf import gaussian_equivalent_from_mtf10
    from voxplane.model.mtf import BeadMtfResult, MtfAxisResult
    # Deliberately inconsistent measured MTF50: it must not influence the model.
    axis = MtfAxisResult((0., 1., 0.), (0., .6, 1.2, 1.8, 2.4), (1., 1.5, .6, .03, .01),
                         1.25, 1.4, .53)
    measured = BeadMtfResult(axis, replace(axis, mtf50=None, unreliable_metrics=('mtf50',)),
                            80., 12., ('原始质控提示',), 'tukey_fft')
    modeled = gaussian_equivalent_from_mtf10(measured)
    assert modeled.analysis_method == 'gaussian_equivalent'
    for result in (modeled.x, modeled.y):
        assert result.mtf10 == 1.4
        assert result.mtf50 == pytest.approx(1.4*math.sqrt(math.log(2)/math.log(10)))
        assert np.interp(result.mtf50, result.frequency, result.mtf) == pytest.approx(.5, abs=1e-15)
        assert np.interp(result.mtf10, result.frequency, result.mtf) == pytest.approx(.1, abs=1e-15)
        assert np.all(np.diff(result.mtf) <= 0) and result.mtf[0] == 1
        assert result.lsf == axis.lsf and result.fwhm == .53
        assert result.unreliable_metrics == ()
    assert modeled.warnings == ('实测频谱：原始质控提示',)
    assert measured.x is axis and measured.y.mtf50 is None
    assert measured.x.mtf50 == 1.25 and measured.y.unreliable_metrics == ('mtf50',)
    assert gaussian_equivalent_from_mtf10(modeled) is modeled


@pytest.mark.parametrize('f10,unreliable', [(None, ()), (float('nan'), ()), (float('inf'), ()),
                                         (0., ()), (-1., ()), (1.4, ('mtf10',))])
def test_gaussian_equivalent_never_invents_an_anchor(f10, unreliable):
    from voxplane.core.bead_mtf import gaussian_equivalent_from_mtf10
    from voxplane.model.mtf import BeadMtfResult, MtfAxisResult
    axis = MtfAxisResult((0., 1., 0.), (0., 1., 2.), (1., .5, .2), .8, f10, .53, unreliable)
    result = gaussian_equivalent_from_mtf10(BeadMtfResult(axis, axis, 0., 1., ()))
    assert result.x.mtf50 is None and result.x.mtf10 is None and result.x.mtf == ()
    assert result.x.unreliable_metrics == unreliable
    assert any('无可靠 MTF10' in warning for warning in result.warnings)


@pytest.mark.parametrize('sample', ['helical_slice11', 'qa_slice151'])
def test_small_phantom_selections_match_complete_roi_and_preserve_validity(sample):
    from pathlib import Path
    from voxplane.core.bead_mtf import compute_mtf_with_context
    with np.load(Path(__file__).parent/'fixtures/mtf/point_sources.npz') as data:
        image = data[sample].astype(float)
    reference = compute_point_source_mtf(image[16:81, 16:81], .1953125, .1953125,
                                         analysis_method='tukey_fft')
    for size in (17, 21, 25, 33):
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                row, col = 48+dy-size//2, 48+dx-size//2
                result = compute_mtf_with_context(image[row:row+size, col:col+size],
                    .1953125, .1953125, context=(image, (row, col)))
                assert any('自动取样' in w for w in result.notes)
                for actual, expected in ((result.x, reference.x), (result.y, reference.y)):
                    assert actual.unreliable_metrics == expected.unreliable_metrics
                    for key in ('mtf50', 'mtf10'):
                        if getattr(expected, key) is None:
                            assert getattr(actual, key) is None
                        else:
                            assert getattr(actual, key) == pytest.approx(getattr(expected, key), rel=1e-5)


def test_background_expansion_keeps_selected_peak_despite_brighter_neighbor():
    from voxplane.core.bead_mtf import compute_mtf_with_context
    image = gaussian(rows=129, columns=129, row_spacing=.1, column_spacing=.1,
                     sigma_x=.2, sigma_y=.2)
    image[64, 89] = 5000  # Brighter outlier in the background ring, not the selected target.
    result = compute_mtf_with_context(image[59:70, 59:70], .1, .1, context=(image, (59, 59)))
    expected = math.sqrt(math.log(10)/(2*math.pi**2*.2**2))
    assert result.x.mtf10 == pytest.approx(expected, rel=.004)
    assert result.y.mtf10 == pytest.approx(expected, rel=.004)
    assert any('自动取样' in w for w in result.notes)


def test_background_expansion_rejects_image_edge_instead_of_padding():
    from voxplane.core.bead_mtf import compute_mtf_with_context
    image = gaussian(rows=33, columns=33, row_spacing=.1, column_spacing=.1,
                     sigma_x=.3, sigma_y=.3)
    with pytest.raises(ValueError, match='影像边缘'):
        compute_mtf_with_context(image[10:23, 10:23], .1, .1, context=(image, (10, 10)))


def test_complete_selection_does_not_change_when_background_context_is_available():
    from voxplane.core.bead_mtf import compute_mtf_with_context
    image = gaussian(rows=129, columns=129, row_spacing=.1, column_spacing=.1,
                     sigma_x=.2, sigma_y=.2)
    roi = image[24:105, 24:105]
    expected = compute_point_source_mtf(roi, .1, .1, analysis_method='tukey_fft')
    assert compute_mtf_with_context(roi, .1, .1, context=(image, (24, 24))) == expected
