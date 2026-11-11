"""Shared display LUT registry for settings, viewports and PET fusion."""
import numpy as np
from .pseudocolor import COLOR_MAP_SPECS, color_lut

COLOR_MAPS = {
    key: (label, tuple("#{:02x}{:02x}{:02x}".format(*rgb) for _, rgb in stops))
    for key, (label, stops) in COLOR_MAP_SPECS.items()
}


def apply_color_map(pixels: np.ndarray | None, name: str) -> np.ndarray | None:
    if pixels is None or pixels.ndim != 2 or name == "grayscale":
        return pixels
    return np.ascontiguousarray(color_lut(name)[pixels])
