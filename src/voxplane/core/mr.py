"""MR display policy and conservative single-volume eligibility.

MR intensities have no universal tissue scale. Echoes, diffusion encodings and
time points must not be silently treated as additional spatial slices.
"""
from math import isfinite
import numpy as np

from voxplane.i18n import message as _msg
from voxplane.model.dicom_types import MrParameters, WindowLevel

MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
MR_MINIMUM_WINDOW = 0.001
from voxplane.core.mr_frames import ENHANCED_MR_CLASSES


def _number(dataset, keyword):
    try:
        value = getattr(dataset, keyword, None)
        if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
            value = value[0]
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, IndexError):
        return None


def _strings(value):
    if isinstance(value, str):
        return (value.upper(),) if value else ()
    return tuple(str(item).upper() for item in (value or ()))


def read_mr_parameters(dataset):
    if str(getattr(dataset, "Modality", "")).upper() != "MR":
        return None
    diffusion = next(iter(getattr(dataset, "MRDiffusionSequence", ())), dataset)
    direction = next(iter(getattr(diffusion, "DiffusionGradientDirectionSequence", ())), diffusion)
    return MrParameters(
        repetition_time=_number(dataset, "RepetitionTime"),
        echo_time=_number(dataset, "EchoTime"),
        inversion_time=_number(dataset, "InversionTime"),
        flip_angle=_number(dataset, "FlipAngle"),
        field_strength=_number(dataset, "MagneticFieldStrength"),
        echo_number=_number(dataset, "EchoNumbers"),
        b_value=_number(diffusion, "DiffusionBValue"),
        diffusion_direction=_strings(getattr(direction, "DiffusionGradientOrientation", ())),
        temporal_position=_number(dataset, "TemporalPositionIdentifier"),
        image_type=_strings(getattr(dataset, "ImageType", ())),
        component=str(getattr(dataset, "ComplexImageComponent", "")).upper(),
        stack_id=str(getattr(dataset, "StackID", "")),
    )


def automatic_mr_window(pixels):
    """Robust finite range; padding has already been replaced with NaN.

    Bound percentile work on large images. Do not remove zero indiscriminately:
    it may be a real signal value, especially in phase/derived images.
    """
    flat = np.asarray(pixels).reshape(-1)
    finite = flat[::max(1, flat.size // 262144)]
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return WindowLevel(0.5, 1.0)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    width = max(float(high - low), MR_MINIMUM_WINDOW)
    return WindowLevel(float((low + high) / 2), width)


def mr_image_error(sop_class_uid, number_of_frames, photometric, samples=1, frame_index=None):
    if not ((sop_class_uid == MR_IMAGE_STORAGE and number_of_frames == 1)
            or (sop_class_uid in ENHANCED_MR_CLASSES and frame_index is not None
                and 0 <= frame_index < number_of_frames)):
        return _msg('mr.unsupportedFormat')
    if photometric not in ('MONOCHROME1', 'MONOCHROME2') or samples != 1:
        return _msg('mr.unsupportedPixels')
    return ''


def validate_mr_dataset(dataset):
    if str(getattr(dataset, 'Modality', '')).upper() != 'MR':
        return
    if 'MOSAIC' in _strings(getattr(dataset, 'ImageType', ())):
        raise ValueError(_msg('mr.mosaic'))
    error = mr_image_error(str(getattr(dataset, 'SOPClassUID', '')),
                           int(getattr(dataset, 'NumberOfFrames', 1)),
                           str(getattr(dataset, 'PhotometricInterpretation', '')),
                           int(getattr(dataset, 'SamplesPerPixel', 1)),
                           getattr(dataset, '_voxplane_frame_index', None))
    if error:
        raise ValueError(error)


def mr_series_error(series, *, volume=False):
    if series.modality.upper() != 'MR':
        return ''
    if not series.instances:
        return _msg('mr.unsupportedPixels')
    for item in series.instances:
        if item.mr_support_error:
            return item.mr_support_error
        if (item.rows or 0) <= 0 or (item.columns or 0) <= 0:
            return _msg('mr.unsupportedPixels')
        if item.mr_parameters and 'MOSAIC' in item.mr_parameters.image_type:
            return _msg('mr.mosaic')
        error = mr_image_error(item.sop_class_uid, item.number_of_frames,
                               item.photometric_interpretation, item.samples_per_pixel, item.frame_index)
        if error:
            return error
    if not volume:
        return ''
    if len(series.instances) < 2:
        return _msg('mr.geometry')
    first = series.instances[0]
    for item in series.instances:
        if (item.mr_parameters != first.mr_parameters
                or item.mr_dimension_indices != first.mr_dimension_indices):
            return _msg('mr.mixedDimensions')
        if item.mr_parameters and {'LOCALIZER', 'SCOUT'}.intersection(item.mr_parameters.image_type):
            return _msg('mr.localizer')
        if (item.rows != first.rows or item.columns != first.columns
                or item.pixel_spacing is None or item.pixel_spacing != first.pixel_spacing
                or item.image_orientation_patient != first.image_orientation_patient
                or item.frame_of_reference_uid != first.frame_of_reference_uid
                or item.photometric_interpretation != first.photometric_interpretation):
            return _msg('mr.geometry')
    try:
        from voxplane.core.volume_view import validate_volume_series
        validate_volume_series(series)
    except ValueError:
        return _msg('mr.geometry')
    return ''


def mr_view_error(series, view):
    if series is None or series.modality.upper() != 'MR' or view == 'tag':
        return ''
    if view in ('4d', 'fusion', 'petctfusion'):
        return _msg('mr.unsupportedView')
    if view in ('2d', 'montage', 'compare2d', 'mpr', '3d'):
        return mr_series_error(series, volume=view in ('mpr', '3d'))
    return ''


def validate_mr_series(series, *, volume=False):
    error = mr_series_error(series, volume=volume)
    if error:
        raise ValueError(error)


def format_mr_parameters(parameters):
    if parameters is None:
        return ''
    values = [('TR', parameters.repetition_time, 'ms'),
              ('TE', parameters.echo_time, 'ms'),
              ('TI', parameters.inversion_time, 'ms'),
              ('FA', parameters.flip_angle, '°'),
              ('B0', parameters.field_strength, 'T'),
              ('b', parameters.b_value, 's/mm²')]
    entries = [f'{label}: {value:g} {unit}' for label, value, unit in values if value is not None]
    return '\n'.join(' · '.join(entries[index:index + 2]) for index in range(0, len(entries), 2))


def split_mr_series(instances, build):
    """Stable display groups; the source Series/SOP UIDs and files stay intact.

    Hash every MR group, including a single group, so incremental imports never
    rename an already displayed group when another echo or time point arrives.
    """
    from collections import defaultdict
    from dataclasses import replace
    from hashlib import sha256
    groups = defaultdict(list)
    if not instances or instances[0].modality.upper() != "MR":
        return [build(instances)]
    for item in instances:
        groups[(item.mr_parameters, item.mr_dimension_indices, bool(item.mr_support_error))].append(item)
    records = []
    for key, members in groups.items():
        record = build(members)
        digest = sha256((record.series_instance_uid + repr(key)).encode()).digest()[:16]
        uid = "2.25." + str(int.from_bytes(digest, "big"))
        p = members[0].mr_parameters
        parts = []
        if p:
            if p.component: parts.append(p.component)
            if p.echo_time is not None: parts.append(f"TE={p.echo_time:g}")
            if p.b_value is not None: parts.append(f"b={p.b_value:g}")
            if p.temporal_position is not None: parts.append(f"t={p.temporal_position:g}")
            if p.diffusion_direction: parts.append("g=" + ",".join(f"{float(v):.3g}" for v in p.diffusion_direction))
            if p.stack_id: parts.append("stack=" + p.stack_id)
        if members[0].mr_dimension_indices:
            parts.append("dim=" + "/".join(str(value[-1]) for value in members[0].mr_dimension_indices))
        description = record.series_description
        if parts: description += " [" + " · ".join(parts) + "]"
        records.append(replace(record, series_instance_uid=uid, series_description=description))
    return records
