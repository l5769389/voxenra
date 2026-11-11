"""Display-only rasterization of a sampled segmentation plane."""
import numpy as np


def segmentation_rgba(mask, color, mode="fill-outline", opacity=30):
    """Keep inner pixel edges (including holes); never smooth or modify the mask.

    Outside the plane is background. A one-pixel inner outline therefore also
    handles image edges, isolated pixels and disconnected regions consistently.
    Fill and outline share one texture to avoid double blending during edits.
    """
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask, :3] = color
    if mode != "outline":
        rgba[mask, 3] = round(255 * opacity / 100)
    if mode != "fill":
        padded = np.pad(mask, 1, constant_values=False)
        interior = (padded[:-2, 1:-1] & padded[2:, 1:-1]
                    & padded[1:-1, :-2] & padded[1:-1, 2:])
        rgba[mask & ~interior, 3] = 255
    return rgba
