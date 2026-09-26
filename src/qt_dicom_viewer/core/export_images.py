"""Full-resolution PNG rendering without viewport annotations or thumbnails."""
from qt_dicom_viewer.i18n import message as _msg

import numpy as np
from pydicom.dataset import Dataset
from pydicom.pixels import apply_color_lut, apply_modality_lut, apply_voi_lut
from PySide6.QtGui import QImage

from qt_dicom_viewer.core.dicom_loader import DicomLoader, _optional_float
from qt_dicom_viewer.model import WindowLevel


def frame_image(pixels, dataset, frame_index=0):
    """Render a decoded frame using its DICOM window and modality transform."""
    # Enhanced objects can override the shared transform/window per frame.
    metadata = Dataset()
    metadata.update(dataset)
    for sequence, index in (("SharedFunctionalGroupsSequence", 0),
                            ("PerFrameFunctionalGroupsSequence", frame_index)):
        groups = getattr(dataset, sequence, [])
        if index < len(groups):
            for keyword in ("PixelValueTransformationSequence", "FrameVOILUTSequence"):
                items = getattr(groups[index], keyword, [])
                if items:
                    metadata.update(items[0])
    from qt_dicom_viewer.core.enhanced_frames import is_enhanced_image, frame_metadata
    if is_enhanced_image(dataset):
        metadata = frame_metadata(dataset, frame_index)
    from qt_dicom_viewer.core.color_image import is_color, color_pixels
    photometric = str(getattr(metadata, "PhotometricInterpretation", ""))
    if is_color(metadata):
        rgb = color_pixels(pixels, metadata)
        fmt = QImage.Format_RGB888 if rgb.shape[2] == 3 else QImage.Format_RGBA8888
        return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], fmt).copy()
    if (pixels.ndim == 2 and str(getattr(dataset, "Modality", "")).upper() in ("CT", "MR")
            and (is_enhanced_image(dataset) or (
                str(getattr(dataset, "SOPClassUID", "")) == "1.2.840.10008.5.1.4.1.1.4"
                and int(getattr(dataset, "NumberOfFrames", 1)) == 1))):
        result = DicomLoader().load_dataset(metadata, None, False,
                    modality_pixels=DicomLoader.rescale_pixels(pixels, metadata))
        pixels = result.image
        image_format = QImage.Format_RGB888 if pixels.ndim == 3 else QImage.Format_Grayscale8
    elif pixels.ndim == 2:
        pixels = np.asarray(apply_modality_lut(pixels, metadata), dtype=np.float64)
        center = _optional_float(getattr(metadata, "WindowCenter", None))
        width = _optional_float(getattr(metadata, "WindowWidth", None))
        if getattr(metadata, "VOILUTSequence", None):
            pixels = apply_voi_lut(pixels, metadata)
            bits = int(metadata.VOILUTSequence[0].LUTDescriptor[2])
            pixels = np.clip(pixels.astype(float) * 255 / (2 ** bits - 1), 0, 255).astype(np.uint8)
            if photometric == "MONOCHROME1":
                pixels = 255 - pixels
        else:
            if center is None or width is None or width < 1:
                finite = pixels[np.isfinite(pixels)]
                low, high = (float(finite.min()), float(finite.max())) if finite.size else (0, 1)
                center, width = (low + high) / 2, max(1, high - low)
            pixels = DicomLoader.apply_window(pixels, WindowLevel(center, width), photometric == "MONOCHROME1")
        image_format = QImage.Format_Grayscale8
    elif pixels.ndim == 3 and pixels.shape[2] in (3, 4):
        if pixels.dtype != np.uint8:
            maximum = (np.iinfo(pixels.dtype).max if photometric == "PALETTE COLOR"
                       else 2 ** int(getattr(metadata, "BitsStored", 8)) - 1)
            pixels = np.clip(pixels.astype(float) * 255 / max(1, maximum), 0, 255).astype(np.uint8)
        image_format = QImage.Format_RGB888 if pixels.shape[2] == 3 else QImage.Format_RGBA8888
    else:
        raise ValueError(_msg('text.0256'))
    pixels = np.ascontiguousarray(pixels)
    height, width = pixels.shape[:2]
    return QImage(pixels.data, width, height, pixels.strides[0], image_format).copy()
