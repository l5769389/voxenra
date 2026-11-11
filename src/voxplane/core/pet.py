"""Classic PET 2D capability checks."""
from voxplane.i18n import message as _msg

from voxplane.model import DicomSeriesRecord


PET_IMAGE_STORAGE_UID = "1.2.840.10008.5.1.4.1.1.128"
ENHANCED_PET_IMAGE_STORAGE_UID = "1.2.840.10008.5.1.4.1.1.130"
LEGACY_CONVERTED_ENHANCED_PET_IMAGE_STORAGE_UID = (
    "1.2.840.10008.5.1.4.1.1.128.1"
)


class UnsupportedPetSeriesError(ValueError):
    pass


def pet_2d_support_error(
    *,
    modality: str,
    sop_class_uid: str,
    number_of_frames: int,
    photometric_interpretation: str,
    series_type: tuple[str, ...],
) -> str:
    """Return an empty string when one instance is eligible for PET 2D v1."""
    if modality.upper() != "PT":
        return ""
    if sop_class_uid in {
        ENHANCED_PET_IMAGE_STORAGE_UID,
        LEGACY_CONVERTED_ENHANCED_PET_IMAGE_STORAGE_UID,
    }:
        return _msg('text.0095')
    if sop_class_uid != PET_IMAGE_STORAGE_UID:
        return _msg('text.0096')
    if number_of_frames != 1:
        return _msg('text.0097')
    if photometric_interpretation.upper() != "MONOCHROME2":
        return _msg('text.0098')

    normalized_type = tuple(value.upper() for value in series_type)
    if len(normalized_type) < 2:
        return _msg('text.0099')
    if normalized_type[0] not in {"STATIC", "WHOLE BODY"}:
        return _msg('text.0100', value1=normalized_type[0])
    if normalized_type[1] != "IMAGE":
        return _msg('text.0101')
    return ""


def validate_pet_2d_series(series: DicomSeriesRecord) -> None:
    """Reject PET encodings whose dimensions cannot be represented by 2D v1."""
    if series.modality.upper() != "PT":
        return

    for instance in series.instances:
        error = pet_2d_support_error(
            modality=instance.modality,
            sop_class_uid=instance.sop_class_uid,
            number_of_frames=instance.number_of_frames,
            photometric_interpretation=(
                instance.photometric_interpretation
            ),
            series_type=instance.pet_series_type,
        )
        if error:
            raise UnsupportedPetSeriesError(error)

    series_types = {
        tuple(value.upper() for value in instance.pet_series_type)
        for instance in series.instances
    }
    if len(series_types) != 1:
        raise UnsupportedPetSeriesError(
            _msg('text.0102')
        )
