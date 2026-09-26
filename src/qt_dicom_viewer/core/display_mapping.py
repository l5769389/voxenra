"""One display-only mapping path for live previews and decoded frame results."""
import numpy as np
from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent, SourcePalette
from qt_dicom_viewer.core.color_maps import apply_color_map
from qt_dicom_viewer.core.ct_display import composite_palette, palette_lut, quantitative_values


def source_palette(dataset):
    if str(getattr(dataset, 'PixelPresentation', '')) != 'COLOR':
        return None
    first, colors = palette_lut(dataset)
    stored = np.arange(first, first+len(colors), dtype=np.float64)
    values, meta = quantitative_values(dataset, stored*float(dataset.RescaleSlope)+float(dataset.RescaleIntercept))
    if len(values)<2 or not np.isfinite(values).all() or values[0] == values[-1]:
        return None
    if values[0] > values[-1]:
        values, colors = values[::-1], colors[::-1]
    return SourcePalette(float(values[0]), float(values[-1]), meta.unit, colors)


def map_display(gray, values, value_meta, overlay=None, palette=None,
                intent=DisplayMappingIntent(), color_map='grayscale'):
    """Custom ranges map physical samples; source mode preserves DICOM VOI/LUT.

    Invalid/padding measurements keep their source appearance. Grayscale samples
    never acquire palette colors merely because a custom range includes them.
    """
    if value_meta.quantification == "color":
        return gray
    if values is not None and intent.applies_to(value_meta.unit):
        finite = np.isfinite(values)
        scaled = np.clip((np.where(finite, values, intent.lower).astype(np.float64)-intent.lower)
                         / (intent.upper-intent.lower), 0, 1)
        if overlay is not None and palette is not None and palette.unit == intent.unit:
            rgb = composite_palette(gray, overlay)
            mask = finite & (overlay[...,3] != 0)
            indices = np.rint(scaled*(len(palette.colors)-1)).astype(np.int64)
            rgb[mask] = palette.colors[indices[mask]]
            return rgb
        if overlay is None:
            mapped = np.rint(scaled*255).astype(np.uint8)
            return apply_color_map(np.where(finite, mapped, gray).astype(np.uint8), color_map)
    return apply_color_map(composite_palette(gray, overlay), color_map)
