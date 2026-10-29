from __future__ import annotations

from functools import lru_cache

import numpy as np


ColorStop = tuple[float, tuple[int, int, int]]


COLOR_MAP_SPECS: dict[str, tuple[str, tuple[ColorStop, ...]]] = {
    "grayscale": (
        "BW",
        ((0.0, (0, 0, 0)), (1.0, (255, 255, 255))),
    ),
    "grayscale-inverted": (
        "BW Inverse (1)",
        ((0.0, (255, 255, 255)), (1.0, (0, 0, 0))),
    ),
    "blackbody": (
        "Black Body (1)",
        (
            (0.0, (0, 0, 0)),
            (0.28, (105, 0, 0)),
            (0.52, (238, 45, 0)),
            (0.72, (255, 205, 0)),
            (1.0, (255, 255, 255)),
        ),
    ),
    "cardiac": (
        "Cardiac",
        (
            (0.0, (0, 255, 48)),
            (0.20, (0, 190, 255)),
            (0.42, (25, 0, 255)),
            (0.64, (255, 0, 160)),
            (0.82, (255, 65, 0)),
            (1.0, (255, 255, 0)),
        ),
    ),
    "flow": (
        "Flow",
        (
            (0.0, (0, 70, 108)),
            (0.28, (0, 120, 235)),
            (0.52, (0, 0, 0)),
            (0.76, (206, 42, 0)),
            (1.0, (255, 245, 205)),
        ),
    ),
    "french": (
        "French",
        (
            (0.0, (10, 20, 45)),
            (0.22, (0, 110, 92)),
            (0.45, (18, 170, 60)),
            (0.66, (225, 194, 5)),
            (0.84, (205, 35, 102)),
            (1.0, (130, 50, 188)),
        ),
    ),
    "gray-rainbow": (
        "GrayRainbow",
        (
            (0.0, (0, 0, 0)),
            (0.18, (34, 25, 88)),
            (0.34, (35, 115, 132)),
            (0.55, (115, 148, 134)),
            (0.76, (205, 185, 164)),
            (1.0, (255, 255, 255)),
        ),
    ),
    "hot-green": (
        "HotGreen",
        (
            (0.0, (0, 0, 0)),
            (0.32, (0, 54, 8)),
            (0.66, (20, 185, 45)),
            (1.0, (245, 255, 235)),
        ),
    ),
    "hot-iron": (
        "Hot Iron (1)",
        (
            (0.0, (0, 0, 0)),
            (0.35, (125, 0, 0)),
            (0.68, (255, 82, 0)),
            (0.86, (255, 225, 0)),
            (1.0, (255, 255, 255)),
        ),
    ),
    "rainbow": (
        "Rainbow",
        (
            (0.0, (0, 0, 60)),
            (0.20, (0, 80, 255)),
            (0.40, (0, 230, 210)),
            (0.60, (60, 220, 0)),
            (0.80, (255, 225, 0)),
            (1.0, (255, 0, 0)),
        ),
    ),
}


def _hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


# Preserve the persisted settings palette IDs alongside the viewport palettes.
COLOR_MAP_SPECS['bwInverse'] = ('BW Inverse (2)', ((0.0, (255, 255, 255)), (1.0, (0, 0, 0))))
COLOR_MAP_SPECS['blackBody'] = ('Black Body (2)', ((0.0, (0, 0, 0)), (0.25, (160, 0, 0)), (0.5, (255, 66, 0)), (0.75, (255, 229, 0)), (1.0, (255, 255, 255))))
COLOR_MAP_SPECS['hotIron'] = ('Hot Iron (2)', ((0.0, (0, 0, 0)), (0.25, (128, 0, 0)), (0.5, (255, 35, 0)), (0.75, (255, 173, 64)), (1.0, (255, 255, 255))))
COLOR_MAP_SPECS['hotMetal'] = ('Hot Metal', ((0.0, (0, 0, 0)), (0.25, (121, 0, 0)), (0.5, (194, 42, 0)), (0.75, (232, 190, 32)), (1.0, (255, 255, 223))))
COLOR_MAP_SPECS['pet'] = ('PET', ((0.0, (0, 0, 0)), (0.25, (0, 123, 123)), (0.5, (89, 0, 200)), (0.75, (231, 126, 33)), (1.0, (255, 255, 255))))

def color_map_options() -> list[dict]:
    return [
        {
            "colorMap": color_map,
            "label": label,
            "stops": [
                {"position": position, "color": _hex(color)}
                for position, color in stops
            ],
        }
        for color_map, (label, stops) in COLOR_MAP_SPECS.items()
    ]


@lru_cache(maxsize=None)
def color_lut(color_map: str) -> np.ndarray:
    try:
        _, stops = COLOR_MAP_SPECS[color_map]
    except KeyError as error:
        raise ValueError(f"Unknown color map: {color_map}") from error

    sample = np.arange(256, dtype=np.float64)
    stop_positions = np.array(
        [position * 255.0 for position, _ in stops],
        dtype=np.float64,
    )
    channels = [
        np.interp(
            sample,
            stop_positions,
            np.array([color[channel] for _, color in stops]),
        )
        for channel in range(3)
    ]
    return np.ascontiguousarray(
        np.rint(np.stack(channels, axis=-1)),
        dtype=np.uint8,
    )


def apply_color_map(pixels: np.ndarray, color_map: str) -> np.ndarray:
    grayscale = np.ascontiguousarray(pixels, dtype=np.uint8)
    if grayscale.ndim != 2:
        raise ValueError("Pseudo-color input must be a two-dimensional image")
    if color_map == "grayscale":
        return grayscale
    if color_map == "grayscale-inverted":
        return np.ascontiguousarray(255 - grayscale, dtype=np.uint8)
    return np.ascontiguousarray(color_lut(color_map)[grayscale])
