"""Source color is presentation data, never a scalar measurement domain."""
import numpy as np
from pydicom.pixels import apply_color_lut


def is_color(dataset):
    return (int(getattr(dataset, "SamplesPerPixel", 1)) > 1
            or str(getattr(dataset, "PhotometricInterpretation", "")).upper() == "PALETTE COLOR")


def color_pixels(pixels, dataset):
    """pydicom decodes YBR to RGB; apply a palette exactly once, before rescale."""
    photometric = str(getattr(dataset, "PhotometricInterpretation", "")).upper()
    if photometric not in {"RGB", "YBR_FULL", "YBR_FULL_422", "YBR_RCT", "YBR_ICT", "PALETTE COLOR"}:
        from qt_dicom_viewer.i18n import message
        raise ValueError(message("viewer.colorEncodingUnsupported"))
    palette = photometric == "PALETTE COLOR"
    rgb = apply_color_lut(pixels, dataset) if palette else np.asarray(pixels)
    if rgb.ndim != 3 or rgb.shape[-1] not in (3, 4):
        raise ValueError("Invalid color frame layout")
    maximum = np.iinfo(rgb.dtype).max if palette else 2 ** int(dataset.BitsStored) - 1
    if rgb.dtype != np.uint8 or maximum != 255:
        rgb = np.rint(np.clip(rgb.astype(np.float64) * (255 / maximum), 0, 255)).astype(np.uint8)
    return np.ascontiguousarray(rgb)
