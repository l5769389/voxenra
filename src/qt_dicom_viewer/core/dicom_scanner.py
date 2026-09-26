from qt_dicom_viewer.i18n import message as _msg
import os
import re
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Iterator, cast

import pydicom

from qt_dicom_viewer.core.mr import read_mr_parameters
from qt_dicom_viewer.core.pet import pet_2d_support_error
from qt_dicom_viewer.model import (
    DicomFolderScanSnapshot,
    DicomInstanceMeta,
    DicomPhaseRecord,
    DicomSeriesRecord,
    PixelSpacing,
)
from qt_dicom_viewer.utils.utils import (
    _as_float,
    _as_float_tuple,
    _as_int,
    _as_str,
    _transfer_syntax_name,
)


# Ordered from explicit temporal identifiers to cautious acquisition-time
# fallbacks. Cross-series geometry validation is required for every source.
_PHASE_VALUE_KEYWORDS: tuple[str, ...] = (
    "TemporalPositionIdentifier",
    "TemporalPositionIndex",
    "PhaseNumber",
    "FrameAcquisitionNumber",
    "NominalPercentageOfCardiacPhase",
    "NominalPercentageOfRespiratoryPhase",
    "RespiratoryCyclePosition",
    "CardiacCyclePosition",
    "TemporalPositionTimeOffset",
    "TriggerTime",
    "ImageTriggerDelay",
    "TriggerTimeOffset",
    "NominalCardiacTriggerDelayTime",
    "NominalCardiacTriggerTimePriorToRPeak",
    "ActualCardiacTriggerTimePriorToRPeak",
    "ActualCardiacTriggerDelayTime",
    "NominalRespiratoryTriggerDelayTime",
    "ActualRespiratoryTriggerDelayTime",
    "FrameReferenceTime",
    "PhaseDelay",
    "PhaseDescription",
    "AcquisitionNumber",
    "FrameAcquisitionDateTime",
    "AcquisitionDateTime",
    "AcquisitionTime",
    "ContentTime",
)

_INTEGER_PHASE_KEYWORDS = frozenset({
    "TemporalPositionIdentifier",
    "TemporalPositionIndex",
    "PhaseNumber",
    "FrameAcquisitionNumber",
    "PhaseDelay",
    "AcquisitionNumber",
})
_TEXT_PHASE_KEYWORDS = frozenset({
    "RespiratoryCyclePosition",
    "CardiacCyclePosition",
    "PhaseDescription",
    "FrameAcquisitionDateTime",
    "AcquisitionDateTime",
    "AcquisitionTime",
    "ContentTime",
})

_SERIES_DESCRIPTION_PHASE_PATTERN = re.compile(
    r"^(?P<base>.+?)[\s_-]*(?:phase|ph)[\s_-]*"
    r"(?P<value>\d+(?:\.\d+)?)(?:\s*%)?$",
    re.IGNORECASE,
)


_GATED_DESCRIPTION_PATTERN = re.compile(
    r"^(?P<base>.+?),\s*Gated,\s*(?P<value>\d+(?:\.\d+)?)\s*%\s*(?P<suffix>[A-Z]?)$",
    re.IGNORECASE,
)


def _optional_str(value: object) -> str | None:
    text = _as_str(value).strip()
    return text or None


def _read_phase_values(
    dataset: pydicom.dataset.Dataset,
) -> tuple[tuple[str, int | float | str], ...]:
    values: list[tuple[str, int | float | str]] = []
    for keyword in _PHASE_VALUE_KEYWORDS:
        raw_value = getattr(dataset, keyword, None)
        if keyword in _INTEGER_PHASE_KEYWORDS:
            value = _as_int(raw_value)
        elif keyword in _TEXT_PHASE_KEYWORDS:
            value = _optional_str(raw_value)
        else:
            value = _as_float(raw_value)
        if value is not None:
            values.append((keyword, value))
    return tuple(values)
def _string_values(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        text = str(value).strip()
        return (text,) if text else ()
    try:
        return tuple(
            text
            for item in value
            if (text := str(item).strip())
        )
    except TypeError:
        text = str(value).strip()
        return (text,) if text else ()


def _iter_visible_files(folder: Path, *, checkpoint=lambda: None, onerror=None):
    for root, dirnames, filenames in os.walk(folder, onerror=onerror):
        # Check even empty directories so large trees remain cancellable.
        checkpoint()
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in sorted(filenames):
            checkpoint()
            if not filename.startswith("."):
                yield Path(root) / filename


def _read_instance(file_path: Path, dataset=None) -> DicomInstanceMeta | None:
    if dataset is None:
        try:
            dataset = pydicom.dcmread(file_path, stop_before_pixels=True)
        except Exception:
            return None

    study_uid = _as_str(getattr(dataset, "StudyInstanceUID", ""))
    series_uid = _as_str(getattr(dataset, "SeriesInstanceUID", ""))
    sop_instance_uid = _as_str(getattr(dataset, "SOPInstanceUID", ""))

    if not series_uid or not sop_instance_uid:
        return None

    image_position = _as_float_tuple(
        getattr(dataset, "ImagePositionPatient", None),
        expected_length=3,
    )
    image_orientation = _as_float_tuple(
        getattr(dataset, "ImageOrientationPatient", None),
        expected_length=6,
    )
    spacing_values = _as_float_tuple(
        getattr(dataset, "PixelSpacing", None),
        expected_length=2,
    )

    pixel_spacing = None
    if spacing_values is not None:
        row_spacing, column_spacing = spacing_values
        if row_spacing > 0 and column_spacing > 0:
            pixel_spacing = PixelSpacing(
                row=row_spacing,
                column=column_spacing,
            )

    modality = _as_str(getattr(dataset, "Modality", ""))
    sop_class_uid = _as_str(getattr(dataset, "SOPClassUID", ""))
    number_of_frames = max(
        1,
        _as_int(getattr(dataset, "NumberOfFrames", None)) or 1,
    )
    photometric_interpretation = _as_str(
        getattr(dataset, "PhotometricInterpretation", "")
    )
    pet_series_type = _string_values(
        getattr(dataset, "SeriesType", None)
    )
    pet_support_error = pet_2d_support_error(
        modality=modality,
        sop_class_uid=sop_class_uid,
        number_of_frames=number_of_frames,
        photometric_interpretation=photometric_interpretation,
        series_type=pet_series_type,
    )

    return DicomInstanceMeta(
        path=file_path,
        patient_name=_as_str(getattr(dataset, "PatientName", "")),
        patient_id=_as_str(getattr(dataset, "PatientID", "")),
        study_description=_as_str(getattr(dataset, "StudyDescription", "")),
        study_instance_uid=study_uid,
        series_description=_as_str(getattr(dataset, "SeriesDescription", "")),
        series_instance_uid=series_uid,
        series_number=_as_int(getattr(dataset, "SeriesNumber", None)),
        instance_number=_as_int(getattr(dataset, "InstanceNumber", None)),
        modality=modality,
        rows=_as_int(getattr(dataset, "Rows", None)),
        columns=_as_int(getattr(dataset, "Columns", None)),
        transfer_syntax=_transfer_syntax_name(dataset),
        sop_instance_uid=sop_instance_uid,
        media_storage_sop_instance_uid=_as_str(
            getattr(getattr(dataset, "file_meta", None), "MediaStorageSOPInstanceUID", "")
        ).strip(),
        image_orientation_patient=cast(
            tuple[float, float, float, float, float, float] | None,
            image_orientation,
        ),
        image_position_patient=cast(
            tuple[float, float, float] | None,
            image_position,
        ),
        pixel_spacing=pixel_spacing,
        slice_thickness=_as_float(getattr(dataset, "SliceThickness", None)),
        study_date=_as_str(getattr(dataset, "StudyDate", "")),
        study_time=_as_str(getattr(dataset, "StudyTime", "")),
        patient_id_issuer=_as_str(getattr(dataset, "IssuerOfPatientID", "")),
        sop_class_uid=sop_class_uid,
        number_of_frames=number_of_frames,
        samples_per_pixel=_as_int(getattr(dataset, "SamplesPerPixel", None)) or 1,
        mr_parameters=read_mr_parameters(dataset),
        frame_index=getattr(dataset, "_voxenra_frame_index", None),
        photometric_interpretation=photometric_interpretation,
        pet_series_type=pet_series_type,
        pet_units=_as_str(getattr(dataset, "Units", "")),
        pet_suv_type=_as_str(getattr(dataset, "SUVType", "")),
        pet_corrected_image=_string_values(
            getattr(dataset, "CorrectedImage", None)
        ),
        pet_decay_correction=_as_str(
            getattr(dataset, "DecayCorrection", "")
        ),
        pet_2d_supported=modality.upper() == "PT" and not pet_support_error,
        pet_2d_support_error=pet_support_error,
        frame_of_reference_uid=_as_str(
            getattr(dataset, "FrameOfReferenceUID", "")
        ),
        phase_values=_read_phase_values(dataset),
        number_of_temporal_positions=_as_int(
            getattr(dataset, "NumberOfTemporalPositions", None)
        ),
        number_of_phases=_as_int(getattr(dataset, "NumberOfPhases", None)),
        patient_sex=_as_str(getattr(dataset, "PatientSex", "")),
        patient_age=_as_str(getattr(dataset, "PatientAge", "")),
        acquisition_datetime=_acquisition_datetime(dataset),
        kvp=_as_float(getattr(dataset, "KVP", None)),
        tube_current_ma=_as_float(
            getattr(dataset, "_voxenra_tube_current_ma", getattr(dataset, "XRayTubeCurrent", None))
        ),
    )


def _read_frames(file_path):
    from qt_dicom_viewer.core.enhanced_frames import is_enhanced_image, is_enhanced_ct, frame_metadata, dimension_indices
    from qt_dicom_viewer.core.ct import ct_frame_group
    try:
        dataset = pydicom.dcmread(file_path, stop_before_pixels=True)
    except Exception:
        return ()
    base = _read_instance(file_path, dataset)
    if base is None:
        return ()
    if not is_enhanced_image(dataset):
        from qt_dicom_viewer.core.color_image import is_color
        if is_color(dataset) and base.number_of_frames > 1:
            return tuple(replace(base, frame_index=index) for index in range(base.number_of_frames))
        return (base,)
    try:
        frames = []
        for index in range(base.number_of_frames):
            metadata = frame_metadata(dataset, index)
            item = _read_instance(file_path, metadata)
            dimensions = dimension_indices(dataset, metadata)
            grouping = ({"ct_dimension_indices": dimensions, "ct_frame_group": ct_frame_group(metadata)}
                        if is_enhanced_ct(dataset) else {"mr_dimension_indices": dimensions})
            frames.append(replace(item, transfer_syntax=base.transfer_syntax,
                                  media_storage_sop_instance_uid=base.media_storage_sop_instance_uid,
                                  **grouping))
        return tuple(frames)
    except (ValueError, TypeError, AttributeError, IndexError) as exc:
        # Keep the source accessible in Tag instead of silently dropping it.
        from qt_dicom_viewer.i18n.messages import Message
        ct_error = (exc.args[0] if exc.args and isinstance(exc.args[0], Message)
                    else _msg("ct.invalidFrames"))
        if is_enhanced_ct(dataset):
            return (replace(base, ct_support_error=ct_error),)
        return (replace(base, mr_support_error=_msg("mr.invalidFrames")),)


def _acquisition_datetime(dataset) -> str:
    """Return a compact, human-readable acquisition timestamp."""
    combined = _as_str(getattr(dataset, "AcquisitionDateTime", ""))
    if combined:
        date_value = combined[:8]
        time_value = combined[8:]
    else:
        date_value = (
            _as_str(getattr(dataset, "AcquisitionDate", ""))
            or _as_str(getattr(dataset, "SeriesDate", ""))
            or _as_str(getattr(dataset, "StudyDate", ""))
        )
        time_value = (
            _as_str(getattr(dataset, "AcquisitionTime", ""))
            or _as_str(getattr(dataset, "SeriesTime", ""))
            or _as_str(getattr(dataset, "StudyTime", ""))
        )

    date_text = date_value
    if len(date_value) >= 8 and date_value[:8].isdigit():
        date_text = (
            f"{date_value[:4]}.{date_value[4:6]}.{date_value[6:8]}"
        )

    main_time = time_value.split(".", 1)[0]
    time_text = time_value
    if len(main_time) >= 2 and main_time[:2].isdigit():
        components = [main_time[:2]]
        if len(main_time) >= 4 and main_time[2:4].isdigit():
            components.append(main_time[2:4])
        if len(main_time) >= 6 and main_time[4:6].isdigit():
            components.append(main_time[4:6])
        time_text = ":".join(components)

    return " ".join(
        value for value in (date_text, time_text) if value
    )


def _build_series_record(
    instances: list[DicomInstanceMeta]
) -> DicomSeriesRecord:
    ordered = tuple(sorted(instances, key=_instance_sort_key))
    first = ordered[0]

    pet_support_error = next(
        (
            instance.pet_2d_support_error
            for instance in ordered
            if instance.pet_2d_support_error
        ),
        "",
    )
    pet_series_types = {
        tuple(value.upper() for value in instance.pet_series_type)
        for instance in ordered
    }
    if (
        not pet_support_error
        and first.modality.upper() == "PT"
        and len(pet_series_types) != 1
    ):
        pet_support_error = _msg('text.0102')

    return DicomSeriesRecord(
        patient_name=first.patient_name,
        patient_id=first.patient_id,
        study_description=first.study_description,
        study_instance_uid=first.study_instance_uid,
        series_description=first.series_description,
        series_instance_uid=first.series_instance_uid,
        series_number=first.series_number,
        modality=first.modality,
        instances=ordered,
        study_date=first.study_date,
        study_time=first.study_time,
        patient_id_issuer=first.patient_id_issuer,
        sop_class_uid=first.sop_class_uid,
        number_of_frames=max(instance.number_of_frames for instance in ordered),
        photometric_interpretation=first.photometric_interpretation,
        pet_series_type=first.pet_series_type,
        pet_units=first.pet_units,
        pet_suv_type=first.pet_suv_type,
        pet_corrected_image=first.pet_corrected_image,
        pet_decay_correction=first.pet_decay_correction,
        pet_2d_supported=(
            first.modality.upper() == "PT" and not pet_support_error
        ),
        pet_2d_support_error=pet_support_error,
        frame_of_reference_uid=first.frame_of_reference_uid,
    )


def _ordered_phase_values(
    source_keyword: str,
    phase_values: Iterable[int | float | str],
) -> list[int | float | str]:
    values = list(phase_values)
    if all(isinstance(value, (int, float)) for value in values):
        return sorted(values, key=float)
    if source_keyword in {
        "FrameAcquisitionDateTime",
        "AcquisitionDateTime",
        "AcquisitionTime",
        "ContentTime",
    }:
        return sorted(values, key=str)
    return values


def _instance_geometry_signature(
    instance: DicomInstanceMeta,
) -> tuple[object, ...] | None:
    position = instance.image_position_patient
    orientation = instance.image_orientation_patient
    spacing = instance.pixel_spacing
    if (
        instance.rows is None
        or instance.columns is None
        or position is None
        or orientation is None
        or spacing is None
    ):
        return None

    return (
        instance.rows,
        instance.columns,
        *(round(value, 4) for value in position),
        *(round(value, 6) for value in orientation),
        round(spacing.row, 6),
        round(spacing.column, 6),
    )


def _link_cross_series_phases(
    series_records: list[DicomSeriesRecord],
) -> list[DicomSeriesRecord]:
    records_by_uid = {
        series.series_instance_uid: series
        for series in series_records
    }
    linked_uids: set[str] = set()
    candidate_sources = (
        # Explicit phase descriptions outrank acquisition/content timestamps:
        # a timestamp may be repeated across phases and split one cycle.
        *_PHASE_VALUE_KEYWORDS[:_PHASE_VALUE_KEYWORDS.index("AcquisitionNumber")],
        "SeriesDescriptionPhaseSuffix",
        *_PHASE_VALUE_KEYWORDS[_PHASE_VALUE_KEYWORDS.index("AcquisitionNumber"):],
    )
    for source_keyword in candidate_sources:
        groups: dict[
            tuple[str, str, str, str, int],
            list[tuple[int | float | str, DicomSeriesRecord]],
        ] = defaultdict(list)

        for original_series in series_records:
            series_uid = original_series.series_instance_uid
            if original_series.modality.upper() == "MR" or series_uid in linked_uids:
                continue

            marker = _cross_series_phase_marker(
                original_series,
                source_keyword=source_keyword,
            )
            if marker is None:
                continue
            phase_value, description_base = marker

            groups[
                (
                    original_series.study_instance_uid,
                    original_series.frame_of_reference_uid,
                    original_series.modality,
                    description_base.casefold(),
                    len(original_series.instances),
                )
            ].append((phase_value, original_series))

        for group_key, candidate_series in groups.items():
            if len(candidate_series) < 2:
                continue

            geometry_groups: dict[
                tuple[tuple[object, ...], ...],
                list[tuple[int | float | str, DicomSeriesRecord]],
            ] = defaultdict(list)
            for phase_value, original_series in candidate_series:
                geometry = _series_geometry_signature(original_series)
                if geometry is not None:
                    geometry_groups[geometry].append(
                        (phase_value, original_series)
                    )

            for phase_series in geometry_groups.values():
                if len(phase_series) < 2:
                    continue
                _apply_cross_series_group(
                    phase_series=phase_series,
                    source_keyword=source_keyword,
                    records_by_uid=records_by_uid,
                    linked_uids=linked_uids,
                )

    return [
        records_by_uid[series.series_instance_uid]
        for series in series_records
    ]


def _apply_cross_series_group(
    *,
    phase_series: list[tuple[int | float | str, DicomSeriesRecord]],
    source_keyword: str,
    records_by_uid: dict[str, DicomSeriesRecord],
    linked_uids: set[str],
) -> None:
    series_by_value = {
        phase_value: series
        for phase_value, series in phase_series
    }
    if len(series_by_value) != len(phase_series):
        return
    if not _matches_expected_phase_count(
        tuple(series_by_value.values())
    ):
        return

    source_values = _ordered_phase_values(
        source_keyword,
        series_by_value,
    )
    phase_identifiers = {
        source_value: (
            source_value
            if isinstance(source_value, int)
            else index
        )
        for index, source_value in enumerate(
            source_values,
            start=1,
        )
    }
    phases = tuple(
        DicomPhaseRecord(
            phase_identifier=phase_identifiers[source_value],
            instances=series_by_value[source_value].instances,
        )
        for source_value in source_values
    )
    for _, original_series in phase_series:
        series_uid = original_series.series_instance_uid
        records_by_uid[series_uid] = replace(
            original_series,
            phases=phases,
            phase_source_keyword=source_keyword,
        )
        linked_uids.add(series_uid)


def _cross_series_phase_marker(
    series: DicomSeriesRecord,
    *,
    source_keyword: str,
) -> tuple[int | float | str, str] | None:
    description_marker = _series_description_phase_marker(
        series.series_description
    )
    if source_keyword == "SeriesDescriptionPhaseSuffix":
        return description_marker

    source_values: set[int | float | str] = set()
    for instance in series.instances:
        source_value = instance.phase_value(source_keyword)
        if source_value is None:
            return None
        if isinstance(source_value, float):
            source_value = round(source_value, 6)
        source_values.add(source_value)
        if len(source_values) > 1:
            return None

    if not source_values:
        return None
    description_base = (
        description_marker[1]
        if description_marker is not None
        else series.series_description.strip()
    )
    if not description_base:
        return None
    return next(iter(source_values)), description_base


def _series_description_phase_marker(
    series_description: str,
) -> tuple[int | float, str] | None:
    match = _SERIES_DESCRIPTION_PHASE_PATTERN.fullmatch(
        series_description.strip()
    )
    if match is None:
        gated = _GATED_DESCRIPTION_PATTERN.fullmatch(series_description.strip())
        if gated is None or not 0 <= float(gated.group("value")) < 100:
            return None
        base = re.sub(r"\^I\d+$", "", gated.group("base").strip(), flags=re.IGNORECASE)
        if not base:
            return None
        return round(float(gated.group("value")), 6), base + ", Gated, %" + gated.group("suffix").upper()

    description_base = match.group("base").rstrip(" _-")
    if not description_base:
        return None
    raw_value = match.group("value")
    phase_value: int | float = (
        int(raw_value)
        if "." not in raw_value
        else round(float(raw_value), 6)
    )
    return phase_value, description_base


def _series_geometry_signature(
    series: DicomSeriesRecord,
) -> tuple[tuple[object, ...], ...] | None:
    if len(series.instances) < 2 or any(
        instance.number_of_frames != 1
        for instance in series.instances
    ):
        return None
    signature = tuple(
        _instance_geometry_signature(instance)
        for instance in series.instances
    )
    if any(item is None for item in signature):
        return None
    if len(set(signature)) != len(signature):
        return None
    return cast(tuple[tuple[object, ...], ...], signature)


def _matches_expected_phase_count(
    series_records: tuple[DicomSeriesRecord, ...],
) -> bool:
    expected_counts = {
        expected_count
        for series in series_records
        for instance in series.instances
        for expected_count in (
            instance.number_of_temporal_positions,
            instance.number_of_phases,
        )
        if expected_count is not None
    }
    return (
        len(expected_counts) <= 1
        and (
            not expected_counts
            or next(iter(expected_counts)) == len(series_records)
        )
    )



def _build_series_from_map(
    series_map: dict[tuple[str, str], list[DicomInstanceMeta]],
    *,
    link_cross_series: bool = True,
) -> list[DicomSeriesRecord]:
    from qt_dicom_viewer.core.mr import split_mr_series
    from qt_dicom_viewer.core.ct import split_ct_series
    series = [record for instances in series_map.values()
              for record in (split_ct_series if instances[0].modality.upper() == "CT"
                             else split_mr_series)(instances, _build_series_record)]
    return (
        _link_cross_series_phases(series)
        if link_cross_series
        else series
    )

class DicomFolderScanner:
    def scan(self,folder_path) -> Iterator[DicomFolderScanSnapshot]:
        folder = Path(folder_path).expanduser()
        if not folder.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder}")

        if not folder.is_dir():
            raise NotADirectoryError(f"Path is not a folder: {folder}")

        yield from self.scan_files(_iter_visible_files(folder), folder=folder)

    def scan_files(self, files, *, folder, cancelled=lambda: False,
                   snapshot_interval=0.0, can_publish=lambda: True,
                   progress=lambda processed, dicom, skipped: None):
        """Group a mixed file selection with the same spatial/4D rules as folders."""
        folder = Path(folder)
        total_file_count = 0
        skipped_file_count = 0
        series_map: dict[tuple[str, str],list[DicomInstanceMeta]] = defaultdict(list)
        instances: list[DicomInstanceMeta] = []
        identities = set()
        seen = set()
        last_snapshot = time.monotonic()
        for file_path in files:
            if cancelled():
                break
            file_path = Path(file_path)
            if file_path.resolve() in seen:
                continue
            seen.add(file_path.resolve())
            total_file_count += 1
            frames = _read_frames(file_path)
            instance = frames[0] if frames else None
            identity = (instance.series_instance_uid, instance.file_identity) if instance else None
            if instance is None or identity in identities:
                skipped_file_count += 1
            else:
                identities.add(identity)
                instances.append(instance)

                key = (
                    instance.study_instance_uid,
                    instance.series_instance_uid,
                )

                series_map[key].extend(frames)

            progress(total_file_count, len(instances), skipped_file_count)
            if time.monotonic() - last_snapshot < snapshot_interval or not can_publish():
                continue
            yield DicomFolderScanSnapshot(
                folder=folder,
                total_file_count=total_file_count,
                dicom_file_count=len(instances),
                skipped_file_count=total_file_count - len(instances),
                series=_build_series_from_map(
                    series_map,
                    link_cross_series=False,
                ),
            )
            # Start the interval after aggregation/consumer work, not before it.
            last_snapshot = time.monotonic()

        progress(total_file_count, len(instances), skipped_file_count)
        yield DicomFolderScanSnapshot(
            folder=folder,
            total_file_count=total_file_count,
            dicom_file_count=len(instances),
            skipped_file_count=total_file_count - len(instances),
            series=_build_series_from_map(series_map),
        )

def _instance_sort_key(
    instance: DicomInstanceMeta,
) -> tuple[int, float, int, str]:
    instance_number = (
        instance.instance_number if instance.instance_number is not None else 1_000_000
    )
    orientation = instance.image_orientation_patient
    position = instance.image_position_patient

    if orientation is not None and position is not None:
        row_x, row_y, row_z, column_x, column_y, column_z = orientation
        normal = (
            row_y * column_z - row_z * column_y,
            row_z * column_x - row_x * column_z,
            row_x * column_y - row_y * column_x,
        )
        spatial_position = sum(
            normal_component * position_component
            for normal_component, position_component in zip(normal, position)
        )
        return 0, spatial_position, instance_number, str(instance.path)

    return 1, float(instance_number), instance_number, str(instance.path)
