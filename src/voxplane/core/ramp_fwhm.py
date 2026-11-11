"""Wire-ramp profile FWHM and geometric slice-thickness conversion.

The ROI must contain one ramp aligned with image X or Y. Average its rows
or columns, subtract the end-background level, then measure the profile.
Catphan wire ramps use thickness = FWHM * tan(23 degrees); this formula
does not apply to a bead's in-plane PSF or to bead-counting ramps.
"""
import math

import numpy as np

from voxplane.core.bead_mtf import _fit_gaussian_lsf, lsf_fwhm
from voxplane.i18n import message as _msg
from voxplane.model.mtf import RampFwhmResult


def ramp_slice_thickness(fwhm: float | None, angle: float) -> float | None:
    if not math.isfinite(angle) or not 0 < angle < 90:
        raise ValueError(_msg('ramp.invalidAngle'))
    if fwhm is None or not math.isfinite(fwhm) or fwhm <= 0:
        return None
    return fwhm * math.tan(math.radians(angle))


def compute_ramp_fwhm(roi: np.ndarray, row_spacing: float, column_spacing: float,
                      *, direction: str = "x", analysis_method: str = "gaussian") -> RampFwhmResult:
    if direction not in ("x", "y") or analysis_method not in ("gaussian", "direct_fft"):
        raise ValueError(_msg('text.0247'))
    if any(not math.isfinite(v) or v <= 0 for v in (row_spacing, column_spacing)):
        raise ValueError(_msg('text.0250'))
    pixels = np.asarray(roi, dtype=np.float64)
    if pixels.ndim != 2 or min(pixels.shape) < 1 or pixels.shape[1 if direction == "x" else 0] < 8:
        raise ValueError(_msg('ramp.shortProfile'))
    if not np.all(np.isfinite(pixels)):
        raise ValueError(_msg('text.0251'))
    spacing = column_spacing if direction == "x" else row_spacing
    profile = pixels.mean(axis=0 if direction == "x" else 1)
    band = max(1, math.ceil(len(profile) * .15))
    ends = np.concatenate((profile[:band], profile[-band:]))
    background = float(np.median(ends))
    signal = profile - background
    peak = float(np.max(signal))
    if not np.all(np.isfinite(signal)) or peak <= np.finfo(float).tiny:
        raise ValueError(_msg('ramp.noPeak'))
    warnings = []
    noise = float(1.4826 * np.median(np.abs(ends - background)))
    if peak < 5 * noise:
        warnings.append(_msg('ramp.lowSignal'))
    if max(abs(signal[0]), abs(signal[-1])) > .05 * peak:
        warnings.append(_msg('ramp.truncated'))
    # A noisy dip below half height can split one broad ramp into several
    # lobes. The nearest-crossing rule then reports only the peak's lobe.
    above_half = signal > .5 * peak
    lobes = int(above_half[0]) + np.count_nonzero(~above_half[:-1] & above_half[1:])
    if lobes > 1:
        warnings.append(_msg('ramp.multipleCrossings'))
    fwhm = lsf_fwhm(signal, spacing)
    fitted = np.array([])
    fitted_background = 0.0
    method = "half_height"
    if fwhm is None:
        warnings.append(_msg('ramp.noCrossing'))
    elif analysis_method == "gaussian":
        # Extra refinement keeps the reported millimetre width stable for
        # longer profiles without changing the point-source MTF fit.
        fitted, sigma, quality = _fit_gaussian_lsf(signal, spacing, refinement_steps=6)
        # The fit includes a free constant C. Keep it for plotting so the
        # raw data and fitted curve use the same baseline and half height.
        fitted_background = float(np.mean(signal - fitted))
        method = "gaussian"
        # A fit must not invent a width for a profile cut off by the ROI.
        if lsf_fwhm(fitted, spacing) is None:
            fwhm = None
            warnings.append(_msg('ramp.noCrossing'))
        else:
            fwhm = 2 * math.sqrt(2 * math.log(2)) * sigma
        if quality < .9:
            warnings.append(_msg('ramp.poorFit', value=f'{quality:.3f}'))
        if np.min(signal) < -.05 * peak:
            warnings.append(_msg('ramp.negativeFit'))
    return RampFwhmResult(tuple(map(float, signal)), tuple(map(float, fitted)),
                          spacing, direction, fwhm, background, tuple(warnings), method,
                          fitted_background)
