"""点源法 MTF 的纯数据模型；方向固定为原始图像列 X、行 Y。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MtfSensitivitySample:
    variant: str
    mtf50: float | None
    mtf10: float | None
    error: str = ""


@dataclass(frozen=True)
class MtfAxisResult:
    lsf: tuple[float, ...]
    frequency: tuple[float, ...]
    mtf: tuple[float, ...]
    mtf50: float | None
    mtf10: float | None
    fwhm: float | None
    # Legacy withheld results stay unavailable until explicitly recalculated.
    unreliable_metrics: tuple[str, ...] = ()
    sensitivity: tuple[MtfSensitivitySample, ...] = ()


@dataclass(frozen=True)
class BeadMtfResult:
    x: MtfAxisResult
    y: MtfAxisResult
    background: float
    noise: float
    warnings: tuple[str, ...]
    analysis_method: str = "direct_fft"
    notes: tuple[str, ...] = ()
    sensitivity_threshold: float | None = None


@dataclass(frozen=True)
class RampFwhmResult:
    """A profile along a wire ramp, distinct from a point-source MTF."""
    profile: tuple[float, ...]
    fitted: tuple[float, ...]
    spacing: float
    direction: str
    fwhm: float | None
    background: float
    warnings: tuple[str, ...]
    analysis_method: str
    fitted_background: float = 0.0
