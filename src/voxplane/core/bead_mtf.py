"""Point-source MTF from measured spectra; optional Gaussian model fitting."""
from dataclasses import replace
import math

import numpy as np

# Load numeric modules with the calculator, before the first Qt worker task.
from numpy.fft import rfft, rfftfreq
from numpy.linalg import solve

from voxplane.i18n import message as _msg
from voxplane.i18n.messages import error_message
from voxplane.model.mtf import BeadMtfResult, MtfAxisResult, MtfSensitivitySample, MtfSampling


MEASUREMENT_METHODS = ("bead", "wire")
ANALYSIS_METHODS = ("direct_fft", "gaussian", "tukey_fft")
# Processing sensitivity limit, not a confidence interval or accuracy bound.
MTF_SENSITIVITY_LIMIT = 0.20
# Formal integration only. Keep support detection/background fitting on the
# existing baseline so this is exactly the former window110 comparison.
MTF_INTEGRATION_SCALE = 1.10


class MtfSupportError(ValueError):
    """The selected source needs more real pixels around its fixed peak."""

    def __init__(self, peak, radii, row_spacing, column_spacing):
        self.peak, self.radii = tuple(peak), tuple(radii)
        self.fallback_warnings = ()
        super().__init__(_msg('mtf.roiSupportIncomplete',
            width=f'{(2*radii[1]+1)*column_spacing:.1f}',
            height=f'{(2*radii[0]+1)*row_spacing:.1f}'))


def compute_mtf_with_context(roi, row_spacing, column_spacing, *, context=None,
                             measurement_method='bead', analysis_method='tukey_fft',
                             sensitivity_threshold=MTF_SENSITIVITY_LIMIT, check_stability=False):
    """Identify the source in the selection; extend only from real image pixels.

    Complete selections retain the existing calculation. With insufficient
    background, lock the original peak and extend around it; never search for
    a replacement source or synthesize padding. Context is a task snapshot
    (image, ROI row/column origin), separate from the measured ROI geometry.
    Processing comparisons are opt-in development diagnostics; normal calls
    calculate only the configured integration support.
    """
    try:
        return compute_point_source_mtf(roi, row_spacing, column_spacing,
            measurement_method=measurement_method, analysis_method=analysis_method,
            sensitivity_threshold=sensitivity_threshold, check_stability=check_stability)
    except MtfSupportError as exc:
        if context is None or (analysis_method != 'tukey_fft' and not exc.fallback_warnings):
            raise
        needed = exc
    image, origin = context
    peak = np.asarray(origin) + needed.peak
    radii = np.asarray(needed.radii)
    for _ in range(8):
        low, high = peak-radii, peak+radii+1
        if np.any(low < 0) or np.any(high > image.shape):
            raise ValueError(_msg('mtf.imageSupportIncomplete'))
        pixels = image[low[0]:high[0], low[1]:high[1]]
        if not np.all(np.isfinite(pixels)):
            raise ValueError(_msg('text.0251'))
        try:
            result = _windowed_point_source_mtf(pixels, row_spacing, column_spacing,
                                               source_index=tuple(radii),
                                               sensitivity_threshold=sensitivity_threshold,
                                               check_stability=check_stability)
        except MtfSupportError as exc:
            # The requested radius is ceil(required support)+1, so at least
            # the deficient axis advances. Do not add padding to an already
            # complete axis on every retry; thin image contexts would fail.
            radii = np.maximum(radii, exc.radii)
            continue
        notice = _msg('mtf.backgroundExpanded',
            width=f'{pixels.shape[1]*column_spacing:.1f}',
            height=f'{pixels.shape[0]*row_spacing:.1f}')
        # Expanded-buffer coordinates must remain relative to the original ROI
        # for saved geometry and overlays on the original image.
        sampling = result.sampling
        if sampling is not None:
            offset = low-np.asarray(origin)
            sampling = replace(sampling, center=(sampling.center[0]+float(offset[1]),
                                                 sampling.center[1]+float(offset[0])))
        return replace(result, notes=(*result.notes, notice), sampling=sampling,
                       warnings=(*needed.fallback_warnings, *result.warnings))
    raise ValueError(_msg('mtf.supportNotConverged'))


def gaussian_equivalent_from_mtf10(result: BeadMtfResult) -> BeadMtfResult:
    """Create a Gaussian *equivalent*, not an LSF fit or measured MTF50.

    M(f) = exp(-ln(10) * (f/f10)**2). Keep the measured result immutable so
    callers can instantly restore it. Invalid/unreliable MTF10 cannot anchor
    a model; do not substitute FWHM, measured MTF50, or another direction.
    """
    if result.analysis_method == 'gaussian_equivalent':
        return result
    warnings = [_msg('mtf.measuredWarning', warning=warning) for warning in result.warnings]

    def equivalent(axis, direction):
        f10 = axis.mtf10
        if (f10 is None or not math.isfinite(f10) or f10 <= 0
                or 'mtf10' in axis.unreliable_metrics):
            warnings.append(_msg('mtf.equivalentUnavailable', direction=direction))
            # A new missing/invalid anchor is not a legacy withheld value.
            return replace(axis, mtf=(), mtf50=None, mtf10=None)
        f50 = f10*math.sqrt(math.log(2.)/math.log(10.))
        # Include the exact anchor/crossing in the plot, making curve and
        # displayed thresholds consistent even on a coarse measured grid.
        frequencies = np.unique(np.r_[axis.frequency, f50, f10])
        response = np.exp(-math.log(10.)*(frequencies/f10)**2)
        return replace(axis, frequency=tuple(map(float, frequencies)),
            mtf=tuple(map(float, response)), mtf50=f50,
            unreliable_metrics=tuple(key for key in axis.unreliable_metrics if key != 'mtf50'),
            sensitivity=tuple(replace(sample,
                mtf50=sample.mtf10*math.sqrt(math.log(2.)/math.log(10.))
                      if sample.mtf10 is not None else None) for sample in axis.sensitivity))

    x, y = equivalent(result.x, 'X'), equivalent(result.y, 'Y')
    return replace(result, x=x, y=y, analysis_method='gaussian_equivalent',
                   warnings=tuple(warnings))


def extract_rect_pixels(pixels: np.ndarray, points, *, minimum_side: int = 8) -> np.ndarray:
    """按像素中心选取矩形，返回独立快照；越界不能静默截取。"""
    if pixels is None or np.ndim(pixels) != 2:
        raise ValueError(_msg('text.0232'))
    columns = [float(p.column) for p in points]
    rows = [float(p.row) for p in points]
    if len(columns) != 2 or not np.all(np.isfinite(columns + rows)):
        raise ValueError(_msg('text.0233'))
    height, width = pixels.shape
    # 图像边界位于最外层像素中心外半个像素处。
    if (min(columns) < -0.5 or max(columns) > width - 0.5
            or min(rows) < -0.5 or max(rows) > height - 0.5):
        raise ValueError(_msg('text.0234'))
    c0, c1 = math.ceil(min(columns)), math.floor(max(columns))
    r0, r1 = math.ceil(min(rows)), math.floor(max(rows))
    if r1 - r0 + 1 < minimum_side or c1 - c0 + 1 < minimum_side:
        raise ValueError(_msg('text.0235'))
    return np.array(pixels[r0:r1 + 1, c0:c1 + 1], dtype=np.float64, copy=True)


def threshold_frequency(frequency: np.ndarray, response: np.ndarray,
                        threshold: float) -> tuple[float | None, bool]:
    """第一次向下穿越阈值；额外穿越仅警告，不取平均或外推。"""
    above = response > threshold
    down = np.flatnonzero(above[:-1] & ~above[1:])
    crossings = np.count_nonzero(above[:-1] != above[1:])
    if len(down) == 0:
        return None, crossings > 1
    i = int(down[0])
    fraction = (response[i] - threshold) / (response[i] - response[i + 1])
    return float(frequency[i] + fraction * (frequency[i + 1] - frequency[i])), crossings > 1


def lsf_fwhm(lsf: np.ndarray, spacing: float, *, peak_index=None) -> float | None:
    """从主峰向两侧找最近的半峰高交点，平台主峰也使用同一约定。"""
    peak_index = int(np.argmax(lsf)) if peak_index is None else peak_index
    peak = float(lsf[peak_index])
    if peak <= 0:
        return None
    half = peak / 2
    left = next((i for i in range(peak_index - 1, -1, -1) if lsf[i] <= half), None)
    right = next((i for i in range(peak_index + 1, len(lsf)) if lsf[i] <= half), None)
    if left is None or right is None:
        return None
    left_crossing = left + (half - lsf[left]) / (lsf[left + 1] - lsf[left])
    right_crossing = right - 1 + (half - lsf[right - 1]) / (lsf[right] - lsf[right - 1])
    return float((right_crossing - left_crossing) * spacing)


def edge_taper(length: int) -> np.ndarray:
    """Symmetric Tukey window, alpha=0.5: middle half is exactly one.

    Taper only the outer quarters of the sampled interval. This reduces the
    weight of ROI boundaries; it neither clips negative lobes nor deconvolves
    the scanner response. No extra runtime dependency is needed.
    """
    position = np.linspace(0.0, 1.0, length)
    edge = np.minimum(position, 1.0 - position)
    weights = np.ones(length)
    tapered = edge < 0.25
    weights[tapered] = 0.5 * (1.0 - np.cos(4.0 * math.pi * edge[tapered]))
    return weights


def subtract_lsf_baseline(lsf: np.ndarray) -> np.ndarray:
    """边缘锚定基线校正:减去连接两侧边缘中位数的直线(弦)。

    二维边界中位数只能去除恒定背景。投影 LSF 中残留的背景倾斜或宽背景
    分量(散射晕、杯状伪影)频谱集中在零频附近,会把归一化 MTF 的低频段
    整体压塌或抬升,使 MTF50/MTF10 严重失真。设计约束:

    - 基线幅度不超过峰值 2% 时视为信号尾部/噪声,原样返回,不扰动干净数据;
    - 弦过陡(如边缘存在局灶亮斑)会把直流量减到非正值,此时退化为减去
      两侧边缘中较小的常数水平;仍非正则不做校正——局灶污染交由 Tukey
      加权与警告处理,不做不可靠的猜测。
    """
    values = np.asarray(lsf, dtype=np.float64)
    n = len(values)
    k = max(3, n // 8)
    left = float(np.median(values[:k]))
    right = float(np.median(values[-k:]))
    start = (k - 1) / 2.0
    chord = left + (right - left) * (np.arange(n) - start) / (n - 1.0 - 2 * start)
    peak = float(np.max(values))
    if peak <= 0:
        return values
    for baseline in (chord, np.full(n, min(left, right))):
        if float(np.max(np.abs(baseline))) <= 0.02 * peak:
            continue
        corrected = values - baseline
        if float(np.sum(corrected)) > 0.05 * float(np.sum(np.abs(corrected))):
            return corrected
    return values


def has_negative_sidelobes(lsf: np.ndarray, noise_floor: float) -> bool:
    """Conservative switching heuristic, not a statistical confidence test.

    Require two adjacent negative samples near the main lobe, deeper than 5%
    of the peak and three times the projected background-noise estimate. A
    distant background fluctuation or a single negative sample is insufficient.
    """
    peak_index = int(np.argmax(lsf))
    peak = float(lsf[peak_index])
    if peak <= 0:
        return False
    width = lsf_fwhm(lsf, 1.0)
    if width is None:
        return False
    radius = max(3, math.ceil(2 * width))
    limit = max(0.05 * peak, 3 * noise_floor)
    for side in (lsf[max(0, peak_index - radius):peak_index],
                 lsf[peak_index + 1:min(len(lsf), peak_index + radius + 1)]):
        below = side < -limit
        if np.any(below[:-1] & below[1:]):
            return True
    return False


def _axis_result(lsf: np.ndarray, spacing: float, direction: str,
                 warnings: list[str], *, taper=False, notes=None) -> MtfAxisResult:
    if not np.all(np.isfinite(lsf)):
        raise ValueError(_msg('text.0236', value1=direction))
    nfft = 1 << (max(1024, 16 * len(lsf)) - 1).bit_length()
    fft_lsf = lsf
    if taper:
        weights = edge_taper(len(lsf))
        if weights[int(np.argmax(lsf))] < 1.0:
            raise ValueError(_msg('mtf.taperOffCenter', direction=direction))
        if np.max(np.abs(lsf[weights < 1.0])) > 0.05 * np.max(lsf):
            warnings.append(_msg('mtf.taperSignal', direction=direction))
        fft_lsf = lsf * weights
        # Magnitude normalization must not hide a nonpositive weighted DC.
        if np.sum(fft_lsf) <= max(np.finfo(float).tiny, np.sum(np.abs(fft_lsf)) * 1e-12):
            raise ValueError(_msg('text.0237', value1=direction))
    if np.sum(fft_lsf) <= max(np.finfo(float).tiny, np.sum(np.abs(fft_lsf))*1e-12):
        raise ValueError(_msg('text.0237', value1=direction))
    spectrum = np.abs(rfft(fft_lsf, n=nfft))
    if not np.all(np.isfinite(spectrum)) or spectrum[0] <= np.finfo(float).tiny:
        raise ValueError(_msg('text.0237', value1=direction))
    frequency = rfftfreq(nfft) / spacing
    response = spectrum / spectrum[0]
    if not np.all(np.isfinite(frequency)) or not np.all(np.isfinite(response)):
        raise ValueError(_msg('text.0238', value1=direction))
    mtf50, multiple50 = threshold_frequency(frequency, response, 0.5)
    mtf10, multiple10 = threshold_frequency(frequency, response, 0.1)
    if multiple50 or multiple10:
        (notes if notes is not None else warnings).append(_msg('text.0239', value1=direction))
    peak = float(np.max(lsf))
    if peak <= 0 or max(abs(float(lsf[0])), abs(float(lsf[-1]))) > 0.05 * peak:
        warnings.append(_msg('text.0240', value1=direction))
    # For the optional 1D taper, check the profile before that taper.
    # The 2D windowed caller separately checks its original projections.
    fwhm = lsf_fwhm(lsf, spacing)
    if fwhm is not None and not math.isfinite(fwhm):
        raise ValueError(_msg('text.0241', value1=direction))
    if fwhm is None:
        warnings.append(_msg('text.0242', value1=direction))
    return MtfAxisResult(tuple(map(float, lsf)), tuple(map(float, frequency)),
                         tuple(map(float, response)), mtf50, mtf10, fwhm)


def _fit_gaussian_lsf(lsf: np.ndarray, spacing: float, *, refinement_steps: int = 4) -> tuple[np.ndarray, float, float]:
    """最小二乘拟合 ``C + A exp(-(x-mu)^2/(2 sigma^2))``。

    背景常数 C 只用于吸收积分后的残余基线；返回的 LSF 不包含该常数，
    因而后续指标表示高斯中心响应本身。
    """
    values = np.asarray(lsf, dtype=np.float64)
    x = np.arange(len(values), dtype=np.float64) * spacing
    span = max(float(x[-1] - x[0]), spacing)
    peak_x = float(x[int(np.argmax(values))])
    mu_low, mu_high = max(float(x[0]), peak_x - span / 4), min(float(x[-1]), peak_x + span / 4)
    sigma_low, sigma_high = spacing * 0.2, span
    best = None
    centered_values = values - np.mean(values)
    total = float(np.sum(centered_values * centered_values))
    tiny = np.finfo(float).tiny

    # 振幅和常数基线使用带截距的一元最小二乘闭式解，避免为每个候选
    # 构造矩阵并调用 lstsq。保持为短向量运算，Qt 工作线程中不启动 BLAS。
    for _ in range(refinement_steps):
        mus = np.linspace(mu_low, mu_high, 35)
        sigmas = np.geomspace(max(sigma_low, spacing * 0.05), sigma_high, 45)
        for mu in mus:
            distance2 = (x - mu) ** 2
            for sigma in sigmas:
                gaussian = np.exp(-distance2 / (2 * sigma ** 2))
                centered_gaussian = gaussian - np.mean(gaussian)
                variance = float(np.sum(centered_gaussian * centered_gaussian))
                if variance <= tiny:
                    continue
                covariance = float(np.sum(centered_values * centered_gaussian))
                amplitude = covariance / variance
                if amplitude <= 0:
                    continue
                error = max(0.0, total - covariance * amplitude)
                if math.isfinite(error) and (best is None or error < best[0]):
                    best = error, float(mu), float(sigma), amplitude
        if best is None:
            break
        _, mu, sigma, _ = best
        mu_radius = max((mu_high - mu_low) / 8, spacing / 100)
        sigma_radius = max((sigma_high - sigma_low) / 8, spacing / 100)
        mu_low, mu_high = max(float(x[0]), mu - mu_radius), min(float(x[-1]), mu + mu_radius)
        sigma_low, sigma_high = max(spacing * 0.05, sigma - sigma_radius), sigma + sigma_radius

    if best is None:
        raise ValueError(_msg('text.0243'))
    error, mu, sigma, amplitude = best
    fitted = amplitude * np.exp(-((x - mu) ** 2) / (2 * sigma ** 2))
    quality = 1.0 if total <= tiny else max(0.0, 1.0 - error / total)
    return fitted, sigma, quality


def _gaussian_axis_result(lsf: np.ndarray, spacing: float, direction: str,
                          warnings: list[str]) -> MtfAxisResult:
    if not np.all(np.isfinite(lsf)):
        raise ValueError(_msg('text.0244', value1=direction))
    fitted, sigma, quality = _fit_gaussian_lsf(lsf, spacing)
    if np.min(lsf) < -0.05 * np.max(lsf):
        warnings.append(_msg('mtf.gaussianNegative', direction=direction))
    if quality < 0.9:
        warnings.append(_msg('text.0245', value1=direction, value2=f'{quality:.3f}'))
    nfft = 1 << (max(1024, 16 * len(lsf)) - 1).bit_length()
    frequency = rfftfreq(nfft) / spacing
    response = np.exp(-2 * math.pi ** 2 * sigma ** 2 * frequency ** 2)

    def crossing(threshold):
        value = math.sqrt(-math.log(threshold) / (2 * math.pi ** 2 * sigma ** 2))
        return value if value <= frequency[-1] else None

    return MtfAxisResult(
        tuple(map(float, fitted)), tuple(map(float, frequency)), tuple(map(float, response)),
        crossing(0.5), crossing(0.1), 2 * math.sqrt(2 * math.log(2)) * sigma,
    )


def _warn_axis_mismatch(x: MtfAxisResult, y: MtfAxisResult, warnings: list[str]) -> None:
    if any(a is not None and b is not None and a > 0 and b > 0
           and min(a, b) < 0.5 * max(a, b)
           for a, b in ((x.mtf50, y.mtf50), (x.mtf10, y.mtf10))):
        warnings.append(_msg('mtf.axisMismatch'))


def _background_plane(pixels: np.ndarray) -> tuple[np.ndarray, float, float, np.ndarray]:
    """Robust affine background fitted only to the outer 10% border.

    Huber reweighting limits isolated border contamination without fitting away
    the central signal or clipping negative PSF lobes. Coordinates are scaled
    to keep the three-parameter normal equations well conditioned.
    """
    h, w = pixels.shape
    yy, xx = np.mgrid[:h, :w]
    xx, yy = (xx - (w-1)/2)/w, (yy - (h-1)/2)/h
    band = max(1, math.ceil(min(h, w)*.1))
    border = np.ones((h, w), dtype=bool)
    border[band:-band, band:-band] = False
    design = np.column_stack((np.ones(np.count_nonzero(border)), xx[border], yy[border]))
    values = pixels[border]
    offset = float(np.median(values))
    values = values - offset
    weights = np.ones(len(values))
    scale_floor = max(float(np.ptp(pixels))*1e-12, np.finfo(float).eps)
    for _ in range(5):
        coefficients = solve(design.T @ (design * weights[:, None]),
                             design.T @ (values * weights))
        residual = values - design @ coefficients
        noise = float(1.4826*np.median(np.abs(residual - np.median(residual))))
        weights = np.minimum(1., 1.5*max(noise, scale_floor)
                             / np.maximum(np.abs(residual), scale_floor))
    plane = offset + coefficients[0] + coefficients[1]*xx + coefficients[2]*yy
    return pixels-plane, float(offset+coefficients[0]), noise, border


def _source_support(pixels: np.ndarray, row_spacing: float, column_spacing: float,
                    *, background_extent: float = 6., source_index=None) -> tuple[
                        np.ndarray, float, float, np.ndarray, np.ndarray, np.ndarray]:
    """Expand support while the taper/background still contains a response.

    FWHM provides an initial scale, not evidence that the full PSF is included.
    A coherent taper-to-background residual can be a positive
    tail or a negative sidelobe. Keep the source fixed while extending into
    real pixels; the caller handles insufficient image/selection coverage.
    """
    scale = np.ones(2)
    for _ in range(8):
        support = _fit_source_support(pixels, row_spacing, column_spacing,
            background_extent=background_extent, source_index=source_index,
            support_scale=scale)
        psf, _, noise, widths, xx, yy = support
        source_index = (int(-yy[0, 0]), int(-xx[0, 0]))
        radius = np.maximum(np.abs(xx)/widths[0], np.abs(yy)/widths[1])
        # Inspect the taper too: by the time a weak tail reaches the background
        # ring, noise can hide it even though truncating it changes the DC/MTF.
        inner = (radius > 3.) & (radius < 4.)
        outer = (radius >= 4.) & (radius < background_extent)
        # Use all four sectors so an isolated adjacent structure does not force
        # unlimited expansion. Winsorization limits outliers without clipping
        # negative values from the actual PSF used by the Fourier calculation.
        peak = float(psf[source_index])
        # Scale each inspected region's stopping floor to 0.1% of weighted
        # signal mass. Otherwise tiny noiseless remnants of an already
        # complete response can demand unbounded background.
        # This is a stopping tolerance, not an accuracy/confidence bound.
        mass = abs(float(np.sum(psf*_source_window(xx, yy, widths))))
        floor = max(abs(peak)*1e-6, np.finfo(float).eps)
        # A narrow tail can occupy less than half a sector. Do not clip its
        # detection samples down to the numerical decision floor when noise is
        # near zero; that would erase every sparse, coherent diagonal response.
        clip_limit = max(6*noise, abs(peak)*.01, floor)
        def contrast(masks):
            samples = [psf[mask] for mask in masks]
            if min(map(len, samples)) < 3:
                return 0., math.inf
            means = [np.mean(np.clip(values, np.median(values)-clip_limit,
                                     np.median(values)+clip_limit)) for values in samples]
            # A narrow strip must use its own sampled area. Using the entire
            # surrounding ring here makes it chase negligible tail remnants
            # and can demand background well beyond a complete response.
            return float(means[0]-means[1]), max(floor, .001*mass/sum(map(len, samples)),
                                                3*noise*math.sqrt(sum(1/len(v) for v in samples)))

        def connected_tail(mask, distance, value, limit):
            if abs(value) <= limit:
                return False
            # Permit an asymmetric PSF, but require a continuous signed trail
            # from outside the core into the taper. A separate isolated bright
            # pixel cannot expand the range merely by occupying one sector.
            sign = np.sign(value)
            for start in (2., 2.5, 3., 3.5):
                samples = psf[mask & (distance >= start) & (distance < start+.5)]
                if len(samples) < 3:
                    return False
                mean = float(np.mean(np.clip(samples, np.median(samples)-clip_limit,
                                             np.median(samples)+clip_limit)))
                if sign*mean <= max(floor, .001*mass/(4*len(samples)), 3*noise/math.sqrt(len(samples))):
                    return False
            return True

        grow = np.zeros(2, dtype=bool)
        for axis, (along, across) in enumerate(((xx/widths[0], yy/widths[1]),
                                               (yy/widths[1], xx/widths[0]))):
            # Attribute a trail to the edge it actually crosses. Enlarging
            # both axes for a horizontal tail needlessly demands vertical
            # background and rejects otherwise complete thin image contexts.
            edge = np.abs(along) >= np.abs(across)
            contrasts, limits, sectors = [], [], []
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                sector = edge & ((xx >= 0) if sx > 0 else (xx < 0)) & ((yy >= 0) if sy > 0 else (yy < 0))
                value, limit = contrast([mask & sector for mask in (inner, outer)])
                contrasts.append(value)
                limits.append(limit)
                sectors.append(sector)
            # A narrow oblique response may occupy just two opposed sectors;
            # a unilateral response must additionally connect to the core.
            grow[axis] = any((contrasts[a] > limits[a] and contrasts[b] > limits[b])
                             or (contrasts[a] < -limits[a] and contrasts[b] < -limits[b])
                             for a, b in ((0, 3), (1, 2)))
            if not grow[axis]:
                grow[axis] = any(connected_tail(sector, radius, value, limit)
                                 for sector, value, limit in zip(sectors, contrasts, limits))
            # Supplement sector averages with narrow axial strips, so a fine
            # response is not diluted by irrelevant pixels in a wide sector.
            sides = []
            for sign in (-1, 1):
                distance = sign*along
                band = np.abs(across) <= 1.
                value, limit = contrast([band & (distance > 3.) & (distance < 4.),
                                         band & (distance >= 4.) & (distance < background_extent)])
                sides.append((value, limit))
                grow[axis] |= connected_tail(band, distance, value, limit)
            grow[axis] |= (all(c > limit for c, limit in sides)
                           or all(c < -limit for c, limit in sides))
        if not np.any(grow):
            return support
        scale[grow] *= 1.5
    raise ValueError(_msg('mtf.supportNotConverged'))


def _fit_source_support(pixels: np.ndarray, row_spacing: float, column_spacing: float,
                        *, background_extent: float, source_index, support_scale: np.ndarray):
    """Refine peak width and a robust background plane at a fixed support scale.

    Require the complete annulus; padding/cropping would invent background.
    """
    psf, background, noise, _ = _background_plane(pixels)
    if np.max(psf) <= 0:
        raise ValueError(_msg('text.0253', value1=_msg('text.0248')))
    peak_index = (np.unravel_index(np.argmax(psf), psf.shape)
                  if source_index is None else source_index)
    if any(i < 2 or i > n-3 for i, n in zip(peak_index, psf.shape)):
        raise ValueError(_msg('mtf.roiIncomplete'))
    py, px = peak_index
    yy, xx = np.mgrid[:pixels.shape[0], :pixels.shape[1]]
    xx, yy = xx-px, yy-py

    def source_widths(values):
        widths = (lsf_fwhm(values[py, :], 1., peak_index=px),
                  lsf_fwhm(values[:, px], 1., peak_index=py))
        if any(w is None or not math.isfinite(w) or w <= 0 for w in widths):
            raise ValueError(_msg('mtf.roiIncomplete'))
        return np.asarray(widths)

    widths = source_widths(psf)
    floor = max(float(np.ptp(pixels))*1e-12, np.finfo(float).eps)
    for _ in range(30):
        support_widths = widths*support_scale
        available = np.array([min(px, pixels.shape[1]-1-px),
                              min(py, pixels.shape[0]-1-py)])
        if np.any(available < background_extent*support_widths):
            radii = (math.ceil(background_extent*support_widths[1])+1,
                     math.ceil(background_extent*support_widths[0])+1)
            raise MtfSupportError(peak_index, radii, row_spacing, column_spacing)
        radius = np.maximum(np.abs(xx)/support_widths[0], np.abs(yy)/support_widths[1])
        annulus = (radius > 4.) & (radius < background_extent)
        if np.count_nonzero(annulus) < 12:
            raise ValueError(_msg('mtf.roiIncomplete'))
        base_weights = np.sin(np.pi*(radius[annulus]-4.)/(background_extent-4.))**2
        design = np.column_stack((np.ones(np.count_nonzero(annulus)),
                                  xx[annulus]/support_widths[0], yy[annulus]/support_widths[1]))
        offset = float(np.median(pixels[annulus]))
        values = pixels[annulus]-offset
        weights = base_weights.copy()
        for _ in range(5):
            coefficients = solve(design.T @ (design*weights[:, None]),
                                 design.T @ (values*weights))
            residual = values-design @ coefficients
            noise = float(1.4826*np.median(np.abs(residual-np.median(residual))))
            weights = base_weights*np.minimum(1., 1.5*max(noise, floor)
                                               / np.maximum(np.abs(residual), floor))
        background = float(offset+coefficients[0])
        psf = pixels-(background+coefficients[1]*xx/support_widths[0]
                     +coefficients[2]*yy/support_widths[1])
        refined = source_widths(psf)
        if np.max(np.abs(refined/widths-1.)) < 1e-6:
            return psf, background, noise, support_widths, xx, yy
        widths = (widths+refined)/2.
    raise ValueError(_msg('mtf.supportNotConverged'))


def _source_window(xx: np.ndarray, yy: np.ndarray, widths: np.ndarray,
                   scale: float = 1.) -> np.ndarray:
    """Keep +/-3 support units unchanged; cosine fade to zero at +/-4."""
    window = np.ones(xx.shape)
    for coordinate, width in ((xx, widths[0]), (yy, widths[1])):
        distance = np.abs(coordinate)/(width*scale)
        window *= .5*(1.+np.cos(np.pi*np.clip(distance-3., 0., 1.)))
    return window


def _windowed_point_source_mtf(pixels: np.ndarray, row_spacing: float, column_spacing: float,
                               *, check_stability: bool = False, source_index=None,
                               sensitivity_threshold=MTF_SENSITIVITY_LIMIT) -> BeadMtfResult:
    psf, background, noise, widths, xx, yy = _source_support(
        pixels, row_spacing, column_spacing, source_index=source_index)
    peak_index = (int(-yy[0, 0]), int(-xx[0, 0]))
    peak = float(psf[peak_index])
    warnings, notes = [], []
    if noise > 0 and peak < 5*noise:
        warnings.append(_msg('text.0254', value1=_msg('text.0248')))
    window = _source_window(xx, yy, widths, MTF_INTEGRATION_SCALE)
    core_widths = np.asarray((lsf_fwhm(psf[peak_index[0], :], 1., peak_index=peak_index[1]),
                             lsf_fwhm(psf[:, peak_index[1]], 1., peak_index=peak_index[0])))
    # Expansion can put a distinct object inside the full-weight region. A
    # fixed peak index prevents target switching but cannot prevent mixing its
    # response with a neighbor. Report this separately from taper truncation.
    distant = ((np.abs(xx) > 2*core_widths[0]) | (np.abs(yy) > 2*core_widths[1])) & (window > 0)
    if np.any(distant) and np.max(psf[distant]*window[distant]) > max(.25*peak, 5*noise):
        warnings.append(_msg('mtf.additionalPeak'))
    tapered = (window > 0) & (window < 1)
    if np.any(tapered) and np.max(np.abs(psf[tapered])) > max(.05*peak, 5*noise):
        warnings.append(_msg('mtf.windowSignal'))

    def axes(response, weights, messages, notices=None, comparison=None):
        # Discard exactly-zero padding so FFT sampling depends on the source
        # support, not on unrelated pixels inside a larger drawn rectangle.
        rows, columns = np.nonzero(weights)
        if not len(rows):
            raise ValueError(_msg('text.0237', value1='X / Y'))
        weighted = response*weights
        # Keep a zero sample outside each end for valid half-height crossings.
        weighted = weighted[max(0, rows.min()-1):rows.max()+2,
                            max(0, columns.min()-1):columns.max()+2]
        outputs = []
        for lsf, spacing, direction in ((weighted.sum(0)*row_spacing, column_spacing, 'X'),
                                         (weighted.sum(1)*column_spacing, row_spacing, 'Y')):
            try:
                axis = _axis_result(lsf, spacing, direction, messages, notes=notices)
                outputs.append(axis if comparison is None else
                               MtfSensitivitySample(comparison, axis.mtf50, axis.mtf10))
            except ValueError as exc:
                if comparison is None:
                    raise
                outputs.append(MtfSensitivitySample(comparison, None, None, error_message(exc)))
        return tuple(outputs)

    x, y = axes(psf, window, warnings, notes)
    if check_stability:
        # Parameter perturbations are diagnostics, never a veto on the baseline.
        comparisons = []
        for name, scale in (('window90', .9), ('window100', 1.), ('background55', None)):
            try:
                if scale is None:
                    response, _, _, other_widths, _, _ = _source_support(
                        pixels, row_spacing, column_spacing, background_extent=5.5,
                        source_index=source_index)
                    weights = _source_window(xx, yy, other_widths, MTF_INTEGRATION_SCALE)
                else:
                    response, weights = psf, _source_window(xx, yy, widths, scale)
                comparisons.append(axes(response, weights, [], [], comparison=name))
            except ValueError as exc:
                failed = MtfSensitivitySample(name, None, None, error_message(exc))
                comparisons.append((failed, failed))
        x = replace(x, sensitivity=tuple(pair[0] for pair in comparisons))
        y = replace(y, sensitivity=tuple(pair[1] for pair in comparisons))
    _warn_axis_mismatch(x, y, warnings)
    sampling = MtfSampling((float(-xx[0, 0]), float(-yy[0, 0])),
                           tuple(map(float, 4*widths*MTF_INTEGRATION_SCALE)),
                           tuple(map(float, 6*widths)), tuple(map(float, 4*widths)))
    notes.append(_msg('mtf.scaledSamplingDetails', percent=f'{100*MTF_INTEGRATION_SCALE:.0f}',
        width=f'{8*widths[0]*column_spacing*MTF_INTEGRATION_SCALE:.2f}',
        height=f'{8*widths[1]*row_spacing*MTF_INTEGRATION_SCALE:.2f}',
        innerWidth=f'{8*widths[0]*column_spacing:.2f}', innerHeight=f'{8*widths[1]*row_spacing:.2f}',
        backgroundWidth=f'{12*widths[0]*column_spacing:.2f}',
        backgroundHeight=f'{12*widths[1]*row_spacing:.2f}'))
    return BeadMtfResult(x, y, background, noise, tuple(dict.fromkeys(warnings)), 'tukey_fft',
                         tuple(dict.fromkeys(notes)), sensitivity_threshold if check_stability else None,
                         sampling, MTF_INTEGRATION_SCALE)


def compute_point_source_mtf(roi: np.ndarray, row_spacing: float,
                             column_spacing: float, *,
                             measurement_method: str = "bead",
                             analysis_method: str = "direct_fft",
                             sensitivity_threshold: float = MTF_SENSITIVITY_LIMIT,
                             check_stability: bool = False) -> BeadMtfResult:
    """Calculate X/Y MTF; check_stability opts into extra audit comparisons."""
    if (isinstance(sensitivity_threshold, bool) or not isinstance(sensitivity_threshold, (float, int))
            or not math.isfinite(sensitivity_threshold) or not .01 <= sensitivity_threshold <= 1.):
        raise ValueError(_msg('mtf.invalidSensitivityThreshold'))
    if measurement_method not in MEASUREMENT_METHODS:
        raise ValueError(_msg('text.0246'))
    if analysis_method not in ANALYSIS_METHODS:
        raise ValueError(_msg('text.0247'))
    source_name = _msg('text.0248') if measurement_method == "bead" else _msg('text.0249')
    try:
        valid_spacing = all(math.isfinite(v) and v > 0 for v in (row_spacing, column_spacing))
    except TypeError:
        valid_spacing = False
    if not valid_spacing:
        raise ValueError(_msg('text.0250'))
    pixels = np.asarray(roi, dtype=np.float64)
    if pixels.ndim != 2 or min(pixels.shape) < 8:
        raise ValueError(_msg('text.0235'))
    if not np.all(np.isfinite(pixels)):
        raise ValueError(_msg('text.0251'))
    if analysis_method == 'tukey_fft':
        return _windowed_point_source_mtf(pixels, row_spacing, column_spacing,
                                            sensitivity_threshold=sensitivity_threshold,
                                            check_stability=check_stability)
    band = max(1, math.ceil(min(pixels.shape) * 0.1))
    border = np.ones(pixels.shape, dtype=bool)
    border[band:-band, band:-band] = False
    background_pixels = pixels[border]
    background = float(np.median(background_pixels))
    noise = float(1.4826 * np.median(np.abs(background_pixels - background)))
    psf = pixels - background
    peak = float(np.max(psf))
    net = float(np.sum(psf))
    magnitude = float(np.sum(np.abs(psf)))
    if not math.isfinite(net) or not math.isfinite(magnitude):
        raise ValueError(_msg('text.0252'))
    if peak <= 0 or net <= max(np.finfo(float).tiny, magnitude * 1e-12):
        raise ValueError(_msg('text.0253', value1=source_name))
    warnings = []
    if noise > 0 and peak < 5 * noise:
        warnings.append(_msg('text.0254', value1=source_name))
    if border[np.unravel_index(np.argmax(psf), psf.shape)]:
        warnings.append(_msg('text.0255'))
    x_lsf_raw = psf.sum(axis=0) * row_spacing
    y_lsf_raw = psf.sum(axis=1) * column_spacing

    def corrected_lsf(raw: np.ndarray) -> np.ndarray:
        # 三类情况跳过锚定校正,保持原始 LSF:
        # 1. 主峰落在窗口外四分之一(截断/严重偏心),边缘中位数是信号;
        # 2. 某一端中位数超过峰值 5%,且从主峰到该端的剖面从未回落到
        #    峰值 2% 以下——说明高边缘是主峰的沿(截断),而不是与主峰
        #    分离的背景(晕/倾斜)。后者剖面会在到达边缘前回落到近零;
        # 3. 边缘窗口内存在深负样本(< -10% 峰值)——深负旁瓣(锐利核的
        #    物理响应)延伸到边缘,属于信号而非背景,交给 Tukey 加权处理。
        peak = float(np.max(raw))
        if peak <= 0:
            return raw
        n = len(raw)
        peak_index = int(np.argmax(raw))
        if min(peak_index, n - 1 - peak_index) < n // 4:
            return raw
        k = max(3, n // 8)
        if min(float(np.min(raw[:k])), float(np.min(raw[-k:]))) < -0.10 * peak:
            return raw

        def truncated(edge_level: float, segment: np.ndarray) -> bool:
            return (edge_level > 0.05 * peak and len(segment) > 0
                    and float(np.min(segment)) > 0.02 * peak)

        if (truncated(float(np.median(raw[:k])), raw[:peak_index])
                or truncated(float(np.median(raw[-k:])), raw[peak_index + 1:])):
            return raw
        return subtract_lsf_baseline(raw)

    x_lsf = corrected_lsf(x_lsf_raw)
    y_lsf = corrected_lsf(y_lsf_raw)
    for raw, corrected, direction in (
            (x_lsf_raw, x_lsf, "X"), (y_lsf_raw, y_lsf, "Y")):
        # 截断检查必须看未校正的 LSF:基线校正会把两端拉零,不能用它
        # 掩盖被 ROI 截断的点源;校正后两端残余由 _axis_result 复查。
        raw_peak = float(np.max(raw))
        if raw_peak <= 0 or max(abs(float(raw[0])), abs(float(raw[-1]))) > 0.05 * raw_peak:
            warnings.append(_msg('text.0240', value1=direction))
        baseline_span = float(np.max(np.abs(raw - corrected)))
        corrected_peak = float(np.max(corrected))
        if corrected_peak > 0 and baseline_span > 0.10 * corrected_peak:
            warnings.append(_msg('mtf.baselineCorrected', direction=direction))
    negative_axes = [direction for lsf, estimate, direction in (
        (x_lsf, noise * math.sqrt(pixels.shape[0]) * row_spacing, "X"),
        (y_lsf, noise * math.sqrt(pixels.shape[1]) * column_spacing, "Y"),
    ) if has_negative_sidelobes(lsf, estimate)]
    if negative_axes and analysis_method == 'gaussian':
        notice = _msg('mtf.autoWeighted', directions=' / '.join(negative_axes))
        try:
            result = _windowed_point_source_mtf(pixels, row_spacing, column_spacing,
                                                sensitivity_threshold=sensitivity_threshold,
                                                check_stability=check_stability)
        except MtfSupportError as exc:
            # Context expansion must retain both the fixed target and the
            # reason for switching methods, even across multiple retries.
            exc.fallback_warnings = (notice,)
            raise
        return replace(result, warnings=(notice, *result.warnings))
    if negative_axes:
        warnings.append(_msg('mtf.negativeMeasured', directions=' / '.join(negative_axes)))
    notes = []
    axis_builder = _gaussian_axis_result if analysis_method == 'gaussian' else _axis_result
    x = axis_builder(x_lsf, column_spacing, "X", warnings, **({"notes": notes} if analysis_method != "gaussian" else {}))
    y = axis_builder(y_lsf, row_spacing, "Y", warnings, **({"notes": notes} if analysis_method != "gaussian" else {}))
    _warn_axis_mismatch(x, y, warnings)
    return BeadMtfResult(x, y, background, noise,
                         tuple(dict.fromkeys(warnings)), analysis_method, tuple(notes))
