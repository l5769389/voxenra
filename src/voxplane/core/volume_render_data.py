"""CPU-only preparation of native 3D buffers; source voxel values stay intact."""
from dataclasses import dataclass

import numpy as np

from voxplane.i18n import message as _msg


@dataclass(frozen=True, slots=True)
class PreparedVolumeData:
    pixels: np.ndarray
    validity: np.ndarray | None = None
    mask_pixels: np.ndarray | None = None


def volume_data_key(volume):
    return (id(volume.modality_pixels), volume.geometry,
            volume.representative_instance_meta.photometric_interpretation,
            volume.representative_instance_meta.mr_parameters is not None)


def prepare_volume_data(volume, padding="mr"):
    """Validate/copy arrays before handing them to GUI-owned VTK objects.

    All-finite float32 volumes share their original buffer. MR padding keeps
    its existing binary mask; fusion layers use their existing padding values.
    """
    geometry = volume.geometry
    pixels = np.ascontiguousarray(volume.modality_pixels, dtype=np.float32)
    if pixels.shape != (geometry.slice_count, geometry.rows, geometry.columns):
        raise ValueError(_msg('text.0015'))
    spacing = (geometry.column_spacing, geometry.row_spacing, geometry.slice_spacing)
    if not all(np.isfinite(v) and v > 0 for v in spacing):
        raise ValueError(_msg('text.0016'))
    finite = np.isfinite(pixels)
    if finite.all():
        return PreparedVolumeData(pixels)
    if not finite.any():
        raise ValueError(_msg('text.0017'))
    if padding in ("ct", "pet"):
        fill = 0 if padding == "pet" else min(-4096., float(np.min(pixels, where=finite, initial=np.inf))-1)
        return PreparedVolumeData(np.where(finite, pixels, fill).astype(np.float32, copy=False))
    mr = volume.representative_instance_meta.mr_parameters is not None
    if not mr or np.isinf(pixels).any():
        raise ValueError(_msg('text.0017'))
    negative = volume.representative_instance_meta.photometric_interpretation == "MONOCHROME1"
    fill = float(np.max(pixels, where=finite, initial=-np.inf) if negative
                 else np.min(pixels, where=finite, initial=np.inf))
    pixels = np.where(finite, pixels, fill).astype(np.float32, copy=False)
    return PreparedVolumeData(pixels, finite, finite.astype(np.uint8)*255)


def prepare_fusion_data(ct, pet):
    return (prepare_volume_data(ct, "ct"), prepare_volume_data(pet, "pet"))
