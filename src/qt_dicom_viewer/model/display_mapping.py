"""Display intent is independent of quantitative pixel values and source windows."""
from dataclasses import dataclass, field
from math import isfinite
import numpy as np


@dataclass(frozen=True, slots=True)
class DisplayMappingIntent:
    mode: str = 'source'
    lower: float = 0.0
    upper: float = 1.0
    unit: str = ''

    def __post_init__(self):
        if self.mode not in ('source', 'custom') or not all(isfinite(v) for v in (self.lower, self.upper)) or not isfinite(self.upper-self.lower) or self.upper <= self.lower:
            raise ValueError('Invalid display mapping range')

    def applies_to(self, unit):
        # Never reuse a numeric range after a frame changes its value domain.
        return self.mode == 'custom' and self.unit == unit


@dataclass(frozen=True, slots=True)
class SourcePalette:
    """Colors in ascending quantitative-value order; detached from source bytes."""
    lower: float
    upper: float
    unit: str
    colors: np.ndarray = field(compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class DisplayMappingCapabilities:
    kind: str  # window, range, palette, transfer
    unit: str
    domain: str
    presets: bool = False
    fixed_lower: float | None = None
    custom_range: bool = False
    grayscale_background: bool = False


def capabilities(*, modality, value_meta, supplemental=False, hu_analysis=True, volume=False):
    unit = value_meta.unit if value_meta else ''
    if value_meta and value_meta.quantification == "color":
        return DisplayMappingCapabilities('color', '', 'presentation')
    if volume:
        return DisplayMappingCapabilities('transfer', unit, 'quantitative' if modality == 'PT' else 'modality')
    if supplemental:
        return DisplayMappingCapabilities('palette', unit, 'quantitative',
            custom_range=True, grayscale_background=True)
    if modality == 'PT':
        return DisplayMappingCapabilities('range', unit, 'quantitative', fixed_lower=0.0)
    if not hu_analysis:
        return DisplayMappingCapabilities('range', unit, 'quantitative', custom_range=True)
    return DisplayMappingCapabilities('window', unit, 'modality', presets=modality == 'CT')
