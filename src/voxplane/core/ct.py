"""Enhanced CT display groups and HU/geometry eligibility.

Keep source UIDs and frame indices intact. HU analysis and volume tools require
HU grayscale frames; derived scalar/color frames may use the 2D pipeline.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from math import isfinite

from voxplane.core.enhanced_frames import ENHANCED_CT_CLASSES, is_enhanced_ct
from voxplane.i18n import message as _msg


# Acquisition timestamps/exposure vary per slice and are deliberately excluded.
# Unknown declared non-spatial dimensions are included separately by the scanner.
_GROUP_ATTRIBUTES = (
    "StackID", "TemporalPositionIdentifier", "TemporalPositionTimeOffset",
    "NominalPercentageOfCardiacPhase", "NominalPercentageOfRespiratoryPhase",
    "NominalCardiacTriggerDelayTime", "NominalRespiratoryTriggerDelayTime",
    "FrameType", "ImageType", "PixelPresentation", "VolumetricProperties",
    "VolumeBasedCalculationTechnique", "AcquisitionType", "ConvolutionKernel",
    "ConvolutionKernelGroup", "ReconstructionAlgorithm", "ReconstructionDiameter",
    "ReconstructionFieldOfView", "RescaleType", "MultienergyCTAcquisition",
)


def _values(value):
    if value is None:
        return ()
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        return (str(value),)
    return tuple(str(v) for v in value)


def ct_frame_group(dataset):
    return tuple((name, _values(getattr(dataset, name))) for name in _GROUP_ATTRIBUTES
                 if name in dataset)


def validate_ct_dataset(dataset):
    if not is_enhanced_ct(dataset):
        return
    frame = getattr(dataset, "_voxplane_frame_index", None)
    if frame is None or not 0 <= frame < int(getattr(dataset, "NumberOfFrames", 0)):
        raise ValueError(_msg("ct.invalidFrames"))
    if (str(getattr(dataset, "Modality", "")).upper() != "CT"
            or int(getattr(dataset, "SamplesPerPixel", 0)) != 1
            or str(getattr(dataset, "PhotometricInterpretation", "")) != "MONOCHROME2"
            or int(getattr(dataset, "Rows", 0)) < 1 or int(getattr(dataset, "Columns", 0)) < 1):
        raise ValueError(_msg("ct.unsupportedPixels"))
    try:
        slope, intercept = float(dataset.RescaleSlope), float(dataset.RescaleIntercept)
        if not isfinite(slope) or not isfinite(intercept) or slope == 0:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise ValueError(_msg("ct.invalidRescale")) from None
    presentation = str(getattr(dataset, "PixelPresentation", "MONOCHROME"))
    if presentation == "COLOR":
        from voxplane.core.ct_display import palette_lut
        try:
            palette_lut(dataset)
        except (AttributeError, TypeError, ValueError):
            raise ValueError(_msg("ct.unsupportedPixels")) from None
    elif presentation != "MONOCHROME":
        raise ValueError(_msg("ct.unsupportedPixels"))


def ct_hu_tools_supported(series):
    return all(i.sop_class_uid not in ENHANCED_CT_CLASSES or (
        dict(i.ct_frame_group).get("RescaleType") == ("HU",)
        and dict(i.ct_frame_group).get("PixelPresentation", ("MONOCHROME",)) == ("MONOCHROME",)
    ) for i in series.instances)


def ct_series_error(series, *, volume=False):
    if series.modality.upper() != "CT":
        return ""
    enhanced = [i for i in series.instances if i.sop_class_uid in ENHANCED_CT_CLASSES]
    if not enhanced:
        return ""
    for item in enhanced:
        if item.ct_support_error:
            return item.ct_support_error
        if item.frame_index is None or not 0 <= item.frame_index < item.number_of_frames:
            return _msg("ct.invalidFrames")
    if not volume:
        return ""
    if not ct_hu_tools_supported(series):
        return _msg("ct.unsupportedUnits")
    first = enhanced[0]
    if len(enhanced) != len(series.instances):
        return _msg("ct.geometry")
    for item in enhanced:
        if (item.ct_frame_group != first.ct_frame_group
                or item.ct_dimension_indices != first.ct_dimension_indices
                or item.rows != first.rows or item.columns != first.columns
                or item.pixel_spacing is None or item.pixel_spacing != first.pixel_spacing
                or item.image_orientation_patient != first.image_orientation_patient
                or item.frame_of_reference_uid != first.frame_of_reference_uid):
            return _msg("ct.geometry")
        group = dict(item.ct_frame_group)
        if (set(group.get("ImageType", ())) & {"LOCALIZER", "SCOUT"}
                or group.get("VolumetricProperties", ("VOLUME",)) != ("VOLUME",)):
            return _msg("ct.geometry")
    try:
        from voxplane.core.volume_view import validate_volume_series
        validate_volume_series(series)
    except ValueError:
        return _msg("ct.geometry")
    return ""


def ct_view_error(series, view):
    if series is None or view == "tag":
        return ""
    return ct_series_error(series, volume=view in ("mpr", "3d", "comparempr", "fusion", "petctfusion", "4d"))


def split_ct_series(instances, build):
    if not instances:
        return []
    if not any(i.sop_class_uid in ENHANCED_CT_CLASSES for i in instances):
        return [build(instances)]
    groups = defaultdict(list)
    for item in instances:
        key = (item.sop_class_uid, item.ct_frame_group, item.ct_dimension_indices,
               bool(item.ct_support_error))
        groups[key].append(item)
    records = []
    for key, members in groups.items():
        record = build(members)
        digest = sha256((record.series_instance_uid + repr(key)).encode()).digest()[:16]
        values = dict(members[0].ct_frame_group)
        parts = []
        for name, label in (("StackID", "stack"), ("TemporalPositionIdentifier", "t"),
                            ("ConvolutionKernel", "kernel"),
                            ("NominalPercentageOfCardiacPhase", "cardiac%"),
                            ("NominalPercentageOfRespiratoryPhase", "resp%")):
            if values.get(name):
                parts.append(label + "=" + "/".join(values[name]))
        if members[0].ct_dimension_indices:
            parts.append("dim=" + "/".join(str(v[-1]) for v in members[0].ct_dimension_indices))
        description = record.series_description + (" [" + " · ".join(parts) + "]" if parts else "")
        records.append(replace(record, series_instance_uid="2.25." + str(int.from_bytes(digest, "big")),
                               series_description=description))
    return records
