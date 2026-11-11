"""Display-space zoom anchoring, independent of image orientation and modality."""
from math import isfinite


def anchored_pan(pan, old_zoom, new_zoom, anchor, size):
    """Return pixel pan keeping the point below anchor fixed on the viewport."""
    width, height = size
    if not all(isfinite(v) and v > 0 for v in size):
        return pan
    x, y = anchor
    if not (isfinite(x) and isfinite(y) and 0 <= x <= width and 0 <= y <= height):
        x, y = width / 2, height / 2
    ratio = new_zoom / old_zoom
    return (pan[0] * ratio + (x - width / 2) * (1 - ratio),
            pan[1] * ratio + (y - height / 2) * (1 - ratio))
