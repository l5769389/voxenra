"""Read Enhanced CT/MR frames without changing their original DICOM identities.

Only standard functional groups are flattened; private nested copies must not
override authoritative geometry. Unknown non-spatial dimension indices remain
part of the grouping key, so they cannot silently become spatial slices.
"""
from copy import copy
from pydicom.dataset import Dataset

ENHANCED_MR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.1"
LEGACY_ENHANCED_MR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.4"
ENHANCED_MR_CLASSES = {ENHANCED_MR_STORAGE, LEGACY_ENHANCED_MR_STORAGE}
ENHANCED_CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2.1"
LEGACY_ENHANCED_CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2.2"
ENHANCED_CT_CLASSES = {ENHANCED_CT_STORAGE, LEGACY_ENHANCED_CT_STORAGE}
_GROUPS = (
    "PixelMeasuresSequence", "PlanePositionSequence", "PlaneOrientationSequence",
    "FrameContentSequence", "MRTimingAndRelatedParametersSequence",
    "MREchoSequence", "MRModifierSequence", "MRImageFrameTypeSequence",
    "PixelValueTransformationSequence", "FrameVOILUTSequence",
)
_CT_GROUPS = (
    "CTImageFrameTypeSequence", "CTAcquisitionTypeSequence",
    "CTReconstructionSequence", "CTExposureSequence", "CTXRayDetailsSequence",
    "CardiacSynchronizationSequence", "RespiratorySynchronizationSequence",
    "TemporalPositionSequence",
)
_SPATIAL_DIMENSIONS = {0x00209057, 0x00200032, 0x00201041}


def is_enhanced_mr(dataset):
    return str(getattr(dataset, "SOPClassUID", "")) in ENHANCED_MR_CLASSES


def is_enhanced_ct(dataset):
    return str(getattr(dataset, "SOPClassUID", "")) in ENHANCED_CT_CLASSES


def is_enhanced_image(dataset):
    return is_enhanced_mr(dataset) or is_enhanced_ct(dataset)


def enhanced_header_error(dataset):
    from voxplane.i18n import message
    try:
        count = int(dataset.NumberOfFrames)
        groups = getattr(dataset, "PerFrameFunctionalGroupsSequence", ())
        if count < 1 or (groups and len(groups) != count):
            raise ValueError()
        shared = getattr(dataset, "SharedFunctionalGroupsSequence", ())
        if len(shared) > 1:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        return message("ct.invalidFrames" if is_enhanced_ct(dataset) else "mr.invalidFrames")
    return ""


def frame_metadata(dataset, frame_index):
    """Detached metadata for one zero-based frame; no pixel/sequence copies."""
    if not is_enhanced_image(dataset):
        if frame_index not in (None, 0):
            raise ValueError("Single-frame object has no requested frame")
        return dataset
    error = enhanced_header_error(dataset)
    if error:
        raise ValueError(error)
    if frame_index is None or not 0 <= frame_index < int(dataset.NumberOfFrames):
        raise ValueError("Enhanced CT/MR requires an explicit valid frame index")
    result = Dataset()
    syntax = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
    result._voxplane_little_endian = syntax.is_little_endian if syntax else dataset.original_encoding[1] is not False
    excluded = {0x52009229, 0x52009230, 0x7fe00010, 0x7fe00008, 0x7fe00009}
    if is_enhanced_ct(dataset):
        # CT frame geometry and quantitative transforms must come from functional
        # groups, not stale classic attributes at the top level of an Enhanced object.
        excluded |= {0x00200032, 0x00200037, 0x00280030, 0x00180050,
                     0x00281052, 0x00281053, 0x00281054, 0x00281050, 0x00281051,
                     0x00283000}
    for element in dataset:
        if element.tag not in excluded:
            result.add(copy(element))
    for group in (*getattr(dataset, "SharedFunctionalGroupsSequence", ()),
                  (dataset.PerFrameFunctionalGroupsSequence[frame_index]
                   if getattr(dataset, "PerFrameFunctionalGroupsSequence", ()) else Dataset())):
        for keyword in _GROUPS + (_CT_GROUPS if is_enhanced_ct(dataset) else ()):
            items = getattr(group, keyword, ())
            if len(items) > 1:
                raise ValueError("Invalid Enhanced CT/MR functional group cardinality")
            if items:
                for element in items[0]:
                    result.add(copy(element))
        for keyword in ("MRDiffusionSequence", "RealWorldValueMappingSequence"):
            if keyword in group:
                result.add(copy(group.data_element(keyword)))
    # These Enhanced attributes replace their classic counterparts for display.
    for enhanced, classic in (("EffectiveEchoTime", "EchoTime"),
                              ("InversionTimes", "InversionTime"),
                              ("TemporalPositionIndex", "TemporalPositionIdentifier"),
                              ("FrameType", "ImageType")):
        if enhanced in result:
            value = getattr(result, enhanced)
            if enhanced == "InversionTimes" and hasattr(value, "__len__"):
                value = value[0] if len(value) else None
            if value is not None:
                setattr(result, classic, value)
    if is_enhanced_ct(dataset) and "XRayTubeCurrentInmA" in result:
        # Enhanced CT records fractional mA; do not coerce into classic IS.
        result._voxplane_tube_current_ma = float(result.XRayTubeCurrentInmA)
    result._voxplane_frame_index = frame_index
    # A missing per-frame geometry is an error, never a fabricated 1mm grid.
    from math import isfinite
    for keyword, length in (("ImagePositionPatient", 3), ("ImageOrientationPatient", 6), ("PixelSpacing", 2)):
        values = getattr(result, keyword, ())
        if len(values) != length or not all(isfinite(float(v)) for v in values):
            raise ValueError("Enhanced CT/MR frame is missing valid patient geometry")
    if any(float(v) <= 0 for v in result.PixelSpacing):
        raise ValueError("Enhanced CT/MR frame has invalid pixel spacing")
    if is_enhanced_ct(dataset):
        import numpy as np
        orientation = np.asarray(result.ImageOrientationPatient, dtype=float).reshape(2, 3)
        if not np.allclose(orientation @ orientation.T, np.eye(2), atol=1e-4):
            raise ValueError("Enhanced CT has invalid orientation direction cosines")
        from voxplane.core.ct import validate_ct_dataset
        validate_ct_dataset(result)
    return result


def dimension_indices(dataset, metadata):
    indices = getattr(metadata, "DimensionIndexValues", ())
    if isinstance(indices, int):
        indices = (indices,)
    definitions = getattr(dataset, "DimensionIndexSequence", ())
    if definitions and len(indices) != len(definitions):
        raise ValueError("Enhanced CT/MR dimension index count does not match its definitions")
    return tuple((str(item.DimensionIndexPointer), str(getattr(item, "FunctionalGroupPointer", "")),
                  str(getattr(item, "DimensionIndexPrivateCreator", "")), int(value))
                 for item, value in zip(definitions, indices)
                 if int(item.DimensionIndexPointer) not in _SPATIAL_DIMENSIONS)
