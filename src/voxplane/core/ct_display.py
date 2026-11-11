"""Supplemental CT color uses stored values; measurements use real-world values.

The grayscale VOI pipeline remains in the modality-rescaled domain. Palette
pixels never pass through windowing, inversion, or a user pseudocolor map.
"""
import numpy as np

from voxplane.model.dicom_types import PixelValueMeta


def palette_lut(dataset):
    channels = []
    descriptor = None
    little = getattr(dataset, '_voxplane_little_endian', True)
    for name in ('Red', 'Green', 'Blue'):
        current = tuple(int(v) for v in getattr(dataset, name+'PaletteColorLookupTableDescriptor'))
        if len(current) != 3 or current[2] not in (8, 16):
            raise ValueError('Invalid supplemental palette descriptor')
        if descriptor is not None and current != descriptor:
            raise ValueError('Inconsistent supplemental palette descriptors')
        descriptor = current
        count, _, bits = current
        count = count or 65536
        data = getattr(dataset, name+'PaletteColorLookupTableData')
        # OW may store 8-bit entries in 16-bit words or pack them into bytes.
        if len(data) == count * 2:
            values = np.frombuffer(data, dtype='<u2' if little else '>u2')
        elif bits == 8 and len(data) == count + count % 2:
            values = np.frombuffer(data, dtype='u1')[:count]
        else:
            raise ValueError('Invalid supplemental palette length')
        if np.any(values > (1 << bits)-1):
            raise ValueError('Palette entries exceed descriptor precision')
        channels.append(np.rint(values.astype(float)*255/((1 << bits)-1)).astype(np.uint8))
    return descriptor[1], np.stack(channels, axis=-1)


def stored_values(dataset, modality_pixels):
    return (modality_pixels.astype(np.float64)-float(dataset.RescaleIntercept))/float(dataset.RescaleSlope)


def supplemental_overlay(dataset, modality_pixels):
    if str(getattr(dataset, 'PixelPresentation', 'MONOCHROME')) != 'COLOR':
        return None
    first, lut = palette_lut(dataset)
    stored = np.rint(stored_values(dataset, modality_pixels))
    valid = np.isfinite(stored)
    indices = np.clip(np.where(valid, stored-first, 0), 0, len(lut)-1).astype(np.int64)
    overlay = np.empty((*stored.shape, 4), np.uint8)
    overlay[..., :3] = lut[indices]
    overlay[..., 3] = np.where(valid & (stored >= first), 255, 0)
    return overlay


def composite_palette(image, overlay):
    if overlay is None:
        return image
    rgb = np.repeat(image[..., None], 3, axis=-1) if image.ndim == 2 else image[..., :3].copy()
    return np.ascontiguousarray(np.where(overlay[..., 3:4] != 0, overlay[..., :3], rgb))


def quantitative_values(dataset, modality_pixels):
    source = str(getattr(dataset, 'RescaleType', '')).strip()
    unit = source if source and source.upper() not in ('US', 'UNSPECIFIED') else 'a.u.'
    if source.upper() == 'HU' and str(getattr(dataset, 'PixelPresentation', 'MONOCHROME')) == 'MONOCHROME':
        return modality_pixels, PixelValueMeta(unit='HU', source_unit=source)
    mappings = getattr(dataset, 'RealWorldValueMappingSequence', ())
    if len(mappings) == 1:
        mapping = mappings[0]
        try:
            units = mapping.MeasurementUnitsCodeSequence
            if len(units) != 1:
                raise ValueError()
            code = units[0]
            unit = str(code.CodeValue if str(code.CodingSchemeDesignator) == 'UCUM' else code.CodeMeaning)
            slope, intercept = float(mapping.RealWorldValueSlope), float(mapping.RealWorldValueIntercept)
            first, last = float(mapping.RealWorldValueFirstValueMapped), float(mapping.RealWorldValueLastValueMapped)
            if not unit or not np.isfinite([slope, intercept, first, last]).all() or slope == 0 or last < first:
                raise ValueError()
            stored = stored_values(dataset, modality_pixels)
            values = np.where((stored >= first) & (stored <= last), stored*slope+intercept, np.nan)
            return np.ascontiguousarray(values, dtype=np.float32), PixelValueMeta(
                unit=unit, source_unit=source, quantification='real-world')
        except (AttributeError, TypeError, ValueError):
            # Never choose an arbitrary mapping or pretend an unhandled LUT is linear.
            unit = source if source and source.upper() not in ('US', 'UNSPECIFIED') else 'a.u.'
    return modality_pixels, PixelValueMeta(unit=unit, source_unit=source,
        warning='Real-world mapping is unavailable; values use the source rescale.' if mappings else None)
