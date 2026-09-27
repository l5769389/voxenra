"""DICOM SEG and TID 1500 SR export of immutable, source-linked results.

No patient diagnosis is inferred from a threshold or a manually drawn region.
Regions on the same source grid share a binary multi-segment object.
Bounded batches retain overlaps; planar and volumetric reports are separate.
"""

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import highdicom as hd
import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.sr.coding import Code
from pydicom.sr.codedict import codes
from pydicom.uid import UID, generate_uid

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.model.measure import (
    AngleMeasurement,
    LengthMeasurement,
    RoiMeasurement,
)
from qt_dicom_viewer.core.measurement_geometry import roi_corners


@dataclass(frozen=True)
class PlanarResult:
    measurement: object
    frame: tuple
    instances: tuple
    is_mpr: bool = False


@dataclass(frozen=True)
class SegmentResult:
    record: dict
    evaluation: object
    instances: tuple


def tracking_uid(identifier):
    try:
        value = UUID(identifier)
    except ValueError:
        value = uuid5(NAMESPACE_URL, identifier)
    return "2.25." + str(value.int)


def _code(value, meaning):
    return Code(value, "99VOXENRA", meaning)


def source_headers(instances, cache):
    result = {}
    for instance in instances:
        path = Path(instance.path)
        if path not in cache:
            dataset = pydicom.dcmread(path, stop_before_pixels=True)
            for key in (
                "StudyInstanceUID",
                "SeriesInstanceUID",
                "SOPInstanceUID",
                "SOPClassUID",
            ):
                if not UID(str(dataset.get(key, ""))).is_valid:
                    raise ValueError(_msg("results.invalidSource"))
            # Type 2 attributes are allowed to be empty, never fabricated.
            for key in (
                "PatientID",
                "PatientName",
                "PatientBirthDate",
                "PatientSex",
                "AccessionNumber",
                "StudyID",
                "StudyDate",
                "StudyTime",
            ):
                if key not in dataset:
                    setattr(dataset, key, "")
            cache[path] = dataset
        dataset = cache[path]
        if str(dataset.SOPInstanceUID) != instance.sop_instance_uid:
            raise ValueError(_msg("results.changedSource"))
        frame = _frame_header(instance, cache)
        if (frame.get("Rows"), frame.get("Columns")) != (
            instance.rows,
            instance.columns,
        ):
            raise ValueError(_msg("results.changedSource"))
        if instance.pixel_spacing is not None and (
            frame.get("PixelSpacing") is None
            or not np.allclose(
                frame.PixelSpacing,
                [instance.pixel_spacing.row, instance.pixel_spacing.column],
                atol=1e-5,
            )
        ):
            raise ValueError(_msg("results.changedSource"))
        for key, expected in [
            ("ImagePositionPatient", instance.image_position_patient),
            ("ImageOrientationPatient", instance.image_orientation_patient),
        ]:
            actual = frame.get(key)
            if expected is not None and (
                actual is None
                or not np.allclose(np.asarray(actual, dtype=float), expected, atol=1e-5)
            ):
                raise ValueError(_msg("results.changedSource"))
        result[str(dataset.SOPInstanceUID)] = dataset
    if not result:
        raise ValueError(_msg("results.invalidSource"))
    if len({str(d.StudyInstanceUID) for d in result.values()}) != 1:
        raise ValueError(_msg("results.mixedStudy"))
    identities = {
        (str(d.PatientID), str(d.PatientName), str(d.get("IssuerOfPatientID", "")))
        for d in result.values()
    }
    if len(identities) != 1:
        raise ValueError(_msg("results.mixedPatient"))
    return list(result.values())


def _frame_header(instance, cache):
    dataset = cache[Path(instance.path)]
    if instance.frame_index is not None:
        from qt_dicom_viewer.core.mr_frames import frame_metadata

        return frame_metadata(dataset, instance.frame_index)
    return dataset


def _segment_description(result, number):
    record, evaluation = result.record, result.evaluation
    algorithm = (
        hd.AlgorithmIdentificationSequence(
            name="Voxenra threshold in ROI",
            family=_code("THRESHOLD", "Threshold segmentation"),
            version="1",
            parameters={
                "threshold": str(evaluation.threshold),
                "unit": str(record["unitLabel"]),
            },
        )
        if record["kind"] == "segmentation" and "mask" not in record
        else None
    )
    color = record.get("color", "#ed55ed").lstrip("#")
    description = hd.seg.SegmentDescription(
        number,
        str(record["name"])[:64],
        _code("REGION", "User-defined region"),
        _code("REGION", "User-defined region"),
        "SEMIAUTOMATIC" if algorithm else "MANUAL",
        algorithm_identification=algorithm,
        tracking_uid=record.get("tracking_uid") or tracking_uid(record["id"]),
        tracking_id=str(record["id"]),
        display_color=hd.color.CIELabColor.from_rgb(
            *(int(color[i : i + 2], 16) for i in (0, 2, 4))
        ),
    )
    if record.get("segment_description"):
        # Preserve the imported tissue codes and algorithm provenance. The mask
        # is unchanged; only its display label/color and segment number vary.
        description = hd.seg.SegmentDescription.from_dataset(
            Dataset.from_json(record["segment_description"])
        )
        description.SegmentNumber = number
        description.SegmentLabel = str(record["name"])[:64]
        description.RecommendedDisplayCIELabValue = list(
            hd.color.CIELabColor.from_rgb(
                *(int(color[i : i + 2], 16) for i in (0, 2, 4))
            ).value
        )
        description.TrackingUID = record.get("tracking_uid") or tracking_uid(
            record["id"]
        )
        if not description.get("TrackingID"):
            description.TrackingID = record["id"]
        if record.get("mask_origin") == "manual":
            # Editing invalidates imported algorithm attribution, while tissue
            # terminology and tracking identity still describe this segment.
            description.SegmentAlgorithmType = "MANUAL"
            for keyword in ("SegmentAlgorithmName", "SegmentationAlgorithmIdentificationSequence"):
                if keyword in description:
                    del description[keyword]
    return description


def build_segmentation(result, cache, number=1, *, additional=()):
    sources = source_headers(result.instances, cache)
    evaluation, record = result.evaluation, result.record
    geometry = evaluation.geometry
    frames = {}
    expected_orientation = (
        *geometry.column_index_direction_patient,
        *geometry.row_index_direction_patient,
    )
    for instance in result.instances:
        frame = _frame_header(instance, cache)
        if (
            frame.get("ImagePositionPatient") is None
            or frame.get("ImageOrientationPatient") is None
            or not np.allclose(
                frame.ImageOrientationPatient, expected_orientation, atol=1e-5
            )
            or not np.allclose(
                frame.PixelSpacing,
                [geometry.row_spacing, geometry.column_spacing],
                atol=1e-5,
            )
            or (frame.Rows, frame.Columns) != (geometry.rows, geometry.columns)
        ):
            raise ValueError(_msg("results.geometryMismatch"))
        index = geometry.patient_to_voxel @ [*map(float, frame.ImagePositionPatient), 1]
        k = round(float(index[0]))
        if (
            not np.allclose(index[:3], [k, 0, 0], atol=1e-3)
            or k in frames
            or not 0 <= k < geometry.slice_count
        ):
            raise ValueError(_msg("results.geometryMismatch"))
        frames[k] = instance
    if len(frames) != geometry.slice_count:
        raise ValueError(_msg("results.geometryMismatch"))
    references = {str(s.get("FrameOfReferenceUID", "")) for s in sources}
    if len(references) != 1 or not UID(next(iter(references))).is_valid:
        raise ValueError(_msg("results.geometryMismatch"))
    results = (result, *additional)
    selections = []
    for item in results:
        if _segment_grid_key(item) != _segment_grid_key(result):
            raise ValueError(_msg("results.geometryMismatch"))
        mask = item.evaluation.mask
        offset = np.asarray(item.evaluation.offset, dtype=int)
        if (
            mask.dtype != bool
            or mask.ndim != 3
            or np.any(offset < 0)
            or np.any(
                offset + mask.shape
                > [geometry.slice_count, geometry.rows, geometry.columns]
            )
        ):
            raise ValueError(_msg("results.geometryMismatch"))
        occupied = np.flatnonzero(mask.any(axis=(1, 2)))
        if not len(occupied):
            raise ValueError(_msg("results.emptySegment", name=item.record["name"]))
        selections.append(occupied + offset[0])
    selected = np.unique(np.concatenate(selections))
    pixels = np.zeros(
        (len(selected), geometry.rows, geometry.columns, len(results)), dtype=np.uint8
    )
    for n, (item, occupied) in enumerate(zip(results, selections, strict=True)):
        mask, offset = item.evaluation.mask, item.evaluation.offset
        pixels[
            np.searchsorted(selected, occupied),
            offset[1] : offset[1] + mask.shape[1],
            offset[2] : offset[2] + mask.shape[2],
            n,
        ] = mask[occupied - offset[0]]
    positions = [
        hd.PlanePositionSequence(
            "PATIENT", (geometry.voxel_to_patient @ [int(k), 0, 0, 1])[:3]
        )
        for k in selected
    ]
    descriptions = [_segment_description(item, n) for n, item in enumerate(results, 1)]
    seg = hd.seg.Segmentation(
        source_images=sources,
        pixel_array=pixels,
        segmentation_type="BINARY",
        segment_descriptions=descriptions,
        series_instance_uid=generate_uid(),
        series_number=900 + number,
        sop_instance_uid=generate_uid(),
        instance_number=1,
        manufacturer="Voxenra",
        manufacturer_model_name="Voxenra",
        software_versions="1.2",
        device_serial_number="Voxenra",
        content_label="SEGMENTATION",
        content_description=(
            str(record["name"])[:64]
            if len(results) == 1
            else "Voxenra segmentation regions"
        ),
        pixel_measures=hd.PixelMeasuresSequence(
            [geometry.row_spacing, geometry.column_spacing],
            geometry.slice_spacing,
            geometry.slice_spacing,
        ),
        plane_orientation=hd.PlaneOrientationSequence("PATIENT", expected_orientation),
        plane_positions=positions,
        omit_empty_frames=True,
    )
    seg.SpecificCharacterSet = "ISO_IR 192"
    seg.SeriesDescription = "Voxenra segmentation"
    seg.ContentCreatorName = ""  # Content Identification Macro: required Type 2.
    # Older SEG readers and highdicom's SR reference helper expect this macro
    # per frame. Both placements are legal; do not duplicate it in Shared FG.
    shared = seg.SharedFunctionalGroupsSequence[0]
    identification = shared.get("SegmentIdentificationSequence")
    if identification is not None:
        for group in seg.PerFrameFunctionalGroupsSequence:
            group.SegmentIdentificationSequence = deepcopy(identification)
        del shared.SegmentIdentificationSequence
    # Resolve the exact selected temporal frame, even when Enhanced MR has
    # several frames at the same position. Never reference a different phase.
    for group in seg.PerFrameFunctionalGroupsSequence:
        position = group.PlanePositionSequence[0].ImagePositionPatient
        k = round(float((geometry.patient_to_voxel @ [*position, 1])[0]))
        instance = frames[k]
        source = cache[Path(instance.path)]
        ref = Dataset()
        ref.ReferencedSOPClassUID, ref.ReferencedSOPInstanceUID = (
            source.SOPClassUID,
            source.SOPInstanceUID,
        )
        if instance.frame_index is not None:
            ref.ReferencedFrameNumber = instance.frame_index + 1
        ref.PurposeOfReferenceCodeSequence = [
            hd.sr.CodedConcept("121322", "DCM", "Source image for image processing")
        ]
        ref.SpatialLocationsPreserved = "YES"
        derivation = Dataset()
        derivation.DerivationCodeSequence = [
            hd.sr.CodedConcept("113076", "DCM", "Segmentation")
        ]
        derivation.SourceImageSequence = [ref]
        group.DerivationImageSequence = [derivation]
    return seg, sources


def _unit(unit):
    known = {
        "HU": codes.UCUM.HounsfieldUnit,
        "SUVbw": Code("g/ml", "UCUM", "g/ml"),
        "g/ml (SUVbw)": Code("g/ml", "UCUM", "g/ml"),
        "Bq/ml": Code("Bq/ml", "UCUM", "Bq/ml"),
        "BQML": Code("Bq/ml", "UCUM", "Bq/ml"),
        "kBq/ml": Code("kBq/ml", "UCUM", "kBq/ml"),
        "counts": Code("{counts}", "UCUM", "counts"),
        "counts/s": Code("{counts}/s", "UCUM", "counts/s"),
        "%": codes.UCUM.Percent,
    }
    return known.get(unit) or _code("UNIT", unit or "Unspecified source units")


def _statistics(values, unit, volume=False):
    result = []
    for key, title in [
        ("mean", "Mean"),
        ("std", "Standard deviation"),
        ("minimum", "Minimum"),
        ("maximum", "Maximum"),
    ]:
        value = values.get(key)
        if value is not None and np.isfinite(value):
            result.append(
                hd.sr.Measurement(_code(key.upper(), title), float(value), _unit(unit))
            )
    count = values.get("pixel_count")
    if count is not None:
        result.append(
            hd.sr.Measurement(
                _code("COUNT", "Voxel count" if volume else "Pixel count"),
                count,
                Code(
                    "{voxels}" if volume else "{pixels}",
                    "UCUM",
                    "voxels" if volume else "pixels",
                ),
            )
        )
    return result


def planar_group(result, cache):
    from dataclasses import asdict

    item, frame = result.measurement, result.frame
    sources = source_headers(result.instances, cache)
    if frame and len(frame) > 6 and frame[6]:
        key = (
            "results.projectedMeasurement"
            if frame[6][0] == "projection"
            else "results.geometryMismatch"
        )
        raise ValueError(_msg(key))
    if frame is None or len(frame) < 6 or len(frame[5]) < 11:
        raise ValueError(_msg("results.missingPlane"))
    pose = np.asarray(frame[5][:11], dtype=float)
    if not np.isfinite(pose).all() or min(pose[:2]) <= 0:
        raise ValueError(_msg("results.missingPlane"))
    axes = pose[5:11].reshape(2, 3)
    if not np.allclose(axes @ axes.T, np.eye(2), atol=1e-5):
        raise ValueError(_msg("results.missingPlane"))
    references = {str(s.get("FrameOfReferenceUID", "")) for s in sources}
    if len(references) != 1 or not UID(next(iter(references))).is_valid:
        raise ValueError(_msg("results.missingPlane"))
    points = item.points
    kind = "angle" if isinstance(item, AngleMeasurement) else str(item.kind)
    metrics = []
    graphic = "POLYLINE"
    if isinstance(item, LengthMeasurement):
        if kind not in ("length", "curve"):
            return None, sources
        if kind == "curve":
            from qt_dicom_viewer.core.curve_geometry import sample_curve
            points = sample_curve(points)
        metrics.append(
            hd.sr.Measurement(codes.SCT.Length, item.length_mm, codes.UCUM.Millimeter)
        )
    elif isinstance(item, AngleMeasurement):
        metrics.append(
            hd.sr.Measurement(codes.SCT.Angle, item.angle, codes.UCUM.Degree)
        )
    elif isinstance(item, RoiMeasurement):
        if kind == "freehand":
            from qt_dicom_viewer.core.freehand_roi import roi_outline
            points = roi_outline(points, item.smooth)
        if kind == "rect":
            points = roi_corners(points)
        if kind == "ellipse":
            a, b = points
            xy = np.array(
                [
                    [(a.column + b.column) / 2, a.row],
                    [(a.column + b.column) / 2, b.row],
                    [a.column, (a.row + b.row) / 2],
                    [b.column, (a.row + b.row) / 2],
                ]
            )
            if abs(b.column - a.column) * pose[1] > abs(b.row - a.row) * pose[0]:
                xy = xy[[2, 3, 0, 1]]
            graphic = "ELLIPSE"
        else:
            xy = np.array([(p.column, p.row) for p in (*points, points[0])])
            graphic = "POLYGON"
        for key, code, unit in [
            ("area_mm2", codes.SCT.Area, codes.UCUM.SquareMillimeter),
            ("width_mm", _code("WIDTH", "Bounding box width"), codes.UCUM.Millimeter),
            (
                "height_mm",
                _code("HEIGHT", "Bounding box height"),
                codes.UCUM.Millimeter,
            ),
            ("perimeter_mm", codes.SCT.Perimeter, codes.UCUM.Millimeter),
        ]:
            value = getattr(item.metrics, key)
            if value is not None:
                metrics.append(hd.sr.Measurement(code, value, unit))
        metrics.extend(_statistics(asdict(item.metrics), item.metrics.unit))
    if not isinstance(item, RoiMeasurement):
        xy = np.array([(p.column, p.row) for p in points])
    patient_points = (
        pose[2:5]
        + xy[:, 0, None] * pose[1] * pose[5:8]
        + xy[:, 1, None] * pose[0] * pose[8:11]
    )
    matching = []
    for instance in result.instances:
        source = _frame_header(instance, cache)
        source_pose = [
            *source.get("PixelSpacing", []),
            *source.get("ImagePositionPatient", []),
            *source.get("ImageOrientationPatient", []),
        ]
        if (
            len(source_pose) == 11
            and (source.Rows, source.Columns) == tuple(frame[3:5])
            and np.allclose(np.asarray(source_pose, dtype=float), pose, atol=1e-5)
            and instance.sop_instance_uid == item.sop_instance_uid
        ):
            matching.append(instance)
    if len(matching) > 1:
        raise ValueError(_msg("results.ambiguousFrame"))
    if matching:
        instance = matching[0]
        source = cache[Path(instance.path)]
        # SCOORD uses pixel corners: the first pixel center is (0.5, 0.5).
        region = hd.sr.ImageRegion(
            "POLYLINE" if graphic == "POLYGON" else graphic,
            xy + 0.5,
            hd.sr.SourceImageForRegion(
                source.SOPClassUID,
                source.SOPInstanceUID,
                [instance.frame_index + 1]
                if instance.frame_index is not None
                else None,
            ),
        )
    else:
        if not result.is_mpr:
            raise ValueError(_msg("results.geometryMismatch"))
        region = hd.sr.ImageRegion3D(graphic, patient_points, next(iter(references)))
    group = hd.sr.PlanarROIMeasurementsAndQualitativeEvaluations(
        tracking_identifier=hd.sr.TrackingIdentifier(
            tracking_uid(item.measurement_id), item.measurement_id
        ),
        referenced_region=region,
        measurements=metrics,
    )
    return group, sources


def segment_group(result, seg, number=1):
    m = result.evaluation.metrics
    metrics = [
        hd.sr.Measurement(codes.SCT.Volume, m["volume"], codes.UCUM.CubicCentimeter)
    ]
    metrics.extend(
        _statistics(
            dict(
                mean=m["mean"],
                std=m["sd"],
                minimum=m["minimum"],
                maximum=m["maximum"],
                pixel_count=m["count"],
            ),
            result.record["unitLabel"],
            True,
        )
    )
    if result.evaluation.threshold is not None:
        metrics.append(
            hd.sr.Measurement(
                _code("THRESHOLD", "Threshold"),
                result.evaluation.threshold,
                _unit(result.record["unitLabel"]),
            )
        )
    return hd.sr.VolumetricROIMeasurementsAndQualitativeEvaluations(
        tracking_identifier=hd.sr.TrackingIdentifier(
            str(seg.SegmentSequence[number - 1].TrackingUID),
            str(seg.SegmentSequence[number - 1].TrackingID),
        ),
        referenced_segment=hd.sr.ReferencedSegment.from_segmentation(seg, number),
        measurements=metrics,
    )


def _segment_grid_key(result):
    g = result.evaluation.geometry
    return (
        tuple(
            (str(i.path), i.sop_instance_uid, i.frame_index) for i in result.instances
        ),
        (g.slice_count, g.rows, g.columns),
        tuple(g.voxel_to_patient.ravel()),
    )


SEG_BATCH_BYTES = 128 * 1024**2


def _segment_batches(segments):
    # Bound the expanded 4D buffer. A singleton keeps the old per-region limit;
    # large collections become independently readable SEG + SR pairs.
    groups = {}
    for result in segments:
        groups.setdefault(_segment_grid_key(result), []).append(result)
    for key, group in groups.items():
        voxel_count = int(np.prod(key[1]))
        batch_size = max(1, SEG_BATCH_BYTES // max(1, voxel_count))
        for start in range(0, len(group), batch_size):
            yield group[start : start + batch_size]


def write_results(
    destination, planar=(), segments=(), *, report=True, cancelled=lambda: False
):
    """Publish atomically. Each SEG has its own SR; planar SRs group by study."""
    destination = Path(destination)
    staging = Path(tempfile.mkdtemp(prefix=".voxenra-results-", dir=destination))
    output = destination / (
        "voxenra-results-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    )
    cache, studies, count = {}, {}, 0

    def check():
        if cancelled():
            raise InterruptedError(_msg("results.cancelled"))

    def add(group, sources, extra=(), scope="planar"):
        uids = {str(s.StudyInstanceUID) for s in sources}
        if len(uids) != 1:
            raise ValueError(_msg("results.mixedStudy"))
        study = studies.setdefault(
            (next(iter(uids)), scope), {"groups": [], "evidence": {}}
        )
        if group is not None:
            study["groups"].append(group)
        for ds in (*sources, *extra):
            study["evidence"][str(ds.SOPInstanceUID)] = ds

    try:
        for index, batch in enumerate(_segment_batches(segments), 1):
            check()
            seg, sources = build_segmentation(
                batch[0], cache, index, additional=batch[1:]
            )
            seg.save_as(staging / f"SEG-{index:03}.dcm", enforce_file_format=True)
            count += 1
            if report:
                for number, result in enumerate(batch, 1):
                    add(
                        segment_group(result, seg, number),
                        sources,
                        [seg],
                        scope=str(seg.SOPInstanceUID),
                    )
        if report:
            for result in planar:
                check()
                group, sources = planar_group(result, cache)
                if group is not None:
                    add(group, sources)
            for index, study in enumerate(studies.values(), 1):
                check()
                evidence = list(study["evidence"].values())
                identities = {
                    (
                        str(d.PatientID),
                        str(d.PatientName),
                        str(d.get("IssuerOfPatientID", "")),
                    )
                    for d in evidence
                }
                if len(identities) != 1:
                    raise ValueError(_msg("results.mixedPatient"))
                context = hd.sr.ObservationContext(
                    observer_device_context=hd.sr.ObserverContext(
                        codes.DCM.Device,
                        hd.sr.DeviceObserverIdentifyingAttributes(
                            tracking_uid("Voxenra"), name="Voxenra"
                        ),
                    )
                )
                content = hd.sr.MeasurementReport(
                    context,
                    _code("IMAGE_MEASUREMENT", "Image-derived measurements"),
                    imaging_measurements=study["groups"],
                )
                sr = hd.sr.Comprehensive3DSR(
                    evidence,
                    content,
                    generate_uid(),
                    1000 + index,
                    generate_uid(),
                    1,
                    manufacturer="Voxenra",
                    is_complete=True,
                    is_final=False,
                    is_verified=False,
                    series_description=(
                        "Voxenra segmentation measurements"
                        if any(
                            d.SOPClassUID == pydicom.uid.SegmentationStorage
                            for d in evidence
                        )
                        else "Voxenra planar measurements"
                    ),
                )
                sr.SpecificCharacterSet = "ISO_IR 192"
                sr.save_as(staging / f"SR-{index:03}.dcm", enforce_file_format=True)
                count += 1
        if not count:
            raise ValueError(_msg("results.noResults"))
        check()
        staging.rename(output)
        return output, count
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
