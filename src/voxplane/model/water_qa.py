"""Single-slice water phantom geometry and measured (not graded) QA results."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WaterPhantom:
    column: float
    row: float
    radius_mm: float
    boundary_coverage: float


@dataclass(frozen=True, slots=True)
class WaterQaSettings:
    roi_diameter_mm: float | None = None
    edge_clearance_mm: float = 10.0
    noise_diameter_mm: float | None = None
    air_diameter_mm: float = 20.0


@dataclass(frozen=True, slots=True)
class WaterQaRoi:
    key: str
    label: str
    column: float
    row: float
    radius_mm: float
    pixel_count: int
    area_mm2: float
    mean_hu: float
    std_hu: float
    minimum_hu: float
    maximum_hu: float
    delta_center_hu: float | None
    group: str = "uniformity"


@dataclass(frozen=True, slots=True)
class WaterQaResult:
    phantom: WaterPhantom | None
    settings: WaterQaSettings
    rois: tuple[WaterQaRoi, ...]
    water_ct_hu: float | None
    noise_hu: float | None
    uniformity_hu: float | None
    consistency_range_hu: float | None
    horizontal_difference_hu: float | None
    vertical_difference_hu: float | None
    noise_range_hu: float | None
    detection_issue: str = ""
    noise_percent: float | None = None
    protocol_version: int = 1
