"""Decode one frame of a representative instance into a small, detached QImage."""

from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset
from pydicom.pixels import apply_modality_lut, apply_color_lut
from qt_dicom_viewer.core.pixel_codecs import decode_pixels
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from qt_dicom_viewer.core.dicom_loader import DicomLoader, _optional_float
from qt_dicom_viewer.model import WindowLevel


def read_series_thumbnail(path: Path, frame_index=None) -> QImage:
    if frame_index is not None:
        from qt_dicom_viewer.core.export_images import frame_image
        import pydicom
        metadata = pydicom.dcmread(path, stop_before_pixels=True)
        image = frame_image(decode_pixels(path, index=frame_index), metadata, frame_index)
        return image.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    metadata = Dataset()
    pixels = decode_pixels(path, index=0, ds_out=metadata,
                         specific_tags=[0x00080060, 0x00080016, 0x00080008])
    photometric = str(getattr(metadata, "PhotometricInterpretation", ""))
    from qt_dicom_viewer.core.color_image import is_color, color_pixels
    if is_color(metadata):
        pixels = color_pixels(pixels, metadata)
    if pixels.ndim == 2 and str(getattr(metadata, "Modality", "")).upper() == "MR":
        pixels = DicomLoader().load_dataset(metadata, None, False,
                    modality_pixels=DicomLoader.rescale_pixels(pixels, metadata)).image
        image_format = QImage.Format_Grayscale8
    elif pixels.ndim == 2:
        pixels = np.asarray(apply_modality_lut(pixels, metadata), dtype=np.float32)
        center = _optional_float(getattr(metadata, "WindowCenter", None))
        width = _optional_float(getattr(metadata, "WindowWidth", None))
        if center is None or width is None or width <= 0:
            finite = pixels[np.isfinite(pixels)]
            low, high = np.percentile(finite, [1, 99]) if finite.size else (0.0, 1.0)
            center, width = float((low + high) / 2), max(1.0, float(high - low))
        pixels = DicomLoader.apply_window(pixels, WindowLevel(center, width), photometric == "MONOCHROME1")
        image_format = QImage.Format_Grayscale8
    elif pixels.ndim == 3 and pixels.shape[2] in (3, 4):
        if pixels.dtype != np.uint8:
            maximum = float(np.iinfo(pixels.dtype).max) if photometric == "PALETTE COLOR" else (
                2 ** int(getattr(metadata, "BitsStored", 8)) - 1)
            pixels = np.clip(pixels.astype(np.float32) * 255 / max(1, maximum), 0, 255).astype(np.uint8)
        image_format = QImage.Format_RGB888 if pixels.shape[2] == 3 else QImage.Format_RGBA8888
    else:
        raise ValueError("Unsupported thumbnail pixel shape")
    pixels = np.ascontiguousarray(pixels)
    height, width = pixels.shape[:2]
    image = QImage(pixels.data, width, height, pixels.strides[0], image_format).copy()
    return image.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
