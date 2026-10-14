from dataclasses import replace

import highdicom as hd
import numpy as np
import pydicom
import pytest
from pydicom.sr.codedict import codes
from pydicom.uid import generate_uid

from qt_dicom_viewer.core.dicom_results import SegmentResult, write_results
from qt_dicom_viewer.core.segmentation_import import read_segmentation
from qt_dicom_viewer.core.segmentation_masks import evaluate_mask, roi_to_mask
from qt_dicom_viewer.core.workspace_state import dumps, loads
from test_dicom_results import source as source, freehand
from test_enhanced_mr import enhanced_dataset, save_and_scan
from qt_dicom_viewer.core.volume_manager import VolumeManager


@pytest.fixture
def external_seg(source, tmp_path):
    series, volume = source
    pixels = np.zeros((*volume.modality_pixels.shape, 2), dtype=bool)
    pixels[0:3:2, 2:7, 2:8, 0] = True
    pixels[2:4, 3:8, 4:9, 1] = True
    descriptions = [
        hd.seg.SegmentDescription(
            i + 1,
            name,
            codes.SCT.AnatomicalStructure,
            codes.SCT.Lung,
            "MANUAL",
            tracking_id=f"region-{i}",
            tracking_uid=generate_uid(),
            display_color=hd.color.CIELabColor.from_rgb(*color),
        )
        for i, (name, color) in enumerate(
            [("区域一", (237, 85, 237)), ("区域二", (67, 198, 220))]
        )
    ]
    seg = hd.seg.Segmentation(
        source_images=[pydicom.dcmread(i.path) for i in series.instances],
        pixel_array=pixels,
        segmentation_type="BINARY",
        segment_descriptions=descriptions,
        series_instance_uid=generate_uid(),
        series_number=300,
        sop_instance_uid=generate_uid(),
        instance_number=1,
        manufacturer="External",
        manufacturer_model_name="External",
        software_versions="1",
        device_serial_number="TEST",
    )
    seg.SpecificCharacterSet = "ISO_IR 192"
    path = tmp_path / "external-seg.dcm"
    seg.save_as(path, enforce_file_format=True)
    return path, pixels, descriptions


def full_mask(record, shape):
    mask = np.zeros(shape, dtype=bool)
    mask[
        tuple(
            slice(a, a + b) for a, b in zip(record["mask_offset"], record["mask"].shape)
        )
    ] = record["mask"]
    return mask


def test_multi_segment_overlap_metadata_workspace_and_reexport(
    source, external_seg, tmp_path
):
    series, volume = source
    path, expected, descriptions = external_seg
    records, evaluations = read_segmentation(path, volume, series.instances)
    assert len(records) == 2
    for i, r in enumerate(records):
        np.testing.assert_array_equal(
            full_mask(r, expected.shape[:3]), expected[..., i]
        )
        assert r["name"] == descriptions[i].SegmentLabel
        assert r["tracking_uid"] == descriptions[i].TrackingUID
        assert evaluations[r["id"]].metrics["count"] == int(expected[..., i].sum())
        restored = loads(dumps(r))
        np.testing.assert_array_equal(restored["mask"], r["mask"])
        assert evaluate_mask(volume, restored).metrics == evaluations[r["id"]].metrics
    records[0]["name"] = "改名"
    records[0]["color"] = "#ffbb55"
    output, _ = write_results(
        tmp_path,
        segments=[
            SegmentResult(r, evaluations[r["id"]], series.instances) for r in records
        ],
    )
    imported = []
    from test_dicom_results import walk

    report_items = list(walk(pydicom.dcmread(output / "SR-001.dcm")))
    for description in descriptions:
        assert any(item.get("UID") == description.TrackingUID for item in report_items)
        assert any(
            item.get("TextValue") == description.TrackingID for item in report_items
        )
    files = list(output.glob("SEG-*.dcm"))
    assert len(files) == 1
    imported, _ = read_segmentation(files[0], volume, series.instances)
    ds = pydicom.dcmread(files[0])
    assert len(imported) == len(ds.SegmentSequence) == 2
    for i, record in enumerate(imported):
        np.testing.assert_array_equal(full_mask(record, expected.shape[:3]), expected[..., i])
        description = ds.SegmentSequence[i]
        assert description.SegmentedPropertyTypeCodeSequence[0].CodeValue == codes.SCT.Lung.value
        assert description.SegmentAlgorithmType == "MANUAL"
        assert description.TrackingUID == descriptions[i].TrackingUID
    assert imported[0]["name"] == "改名"
    assert imported[0]["color"] == "#ffbb55"


def test_cropped_flipped_frames_align_to_native_grid(source, external_seg, tmp_path):
    series, volume = source
    path, expected, _ = external_seg
    ds = pydicom.dcmread(path)
    pixels = ds.pixel_array[:, 1:8, 2:9][:, :, ::-1]
    shared = ds.SharedFunctionalGroupsSequence[0]
    orientation = np.array(
        shared.PlaneOrientationSequence[0].ImageOrientationPatient, dtype=float
    )
    spacing = shared.PixelMeasuresSequence[0].PixelSpacing
    for group in ds.PerFrameFunctionalGroupsSequence:
        pos = group.PlanePositionSequence[0]
        pos.ImagePositionPatient = (
            np.array(pos.ImagePositionPatient)
            + orientation[:3] * (2 + 6) * spacing[1]
            + orientation[3:] * spacing[0]
        ).tolist()
    shared.PlaneOrientationSequence[0].ImageOrientationPatient = [
        *(-orientation[:3]),
        *orientation[3:],
    ]
    ds.Rows, ds.Columns = pixels.shape[1:]
    ds.PixelData = pydicom.pixels.pack_bits(pixels)
    ds.save_as(path, enforce_file_format=True)
    records, _ = read_segmentation(path, volume, series.instances)
    for i, r in enumerate(records):
        np.testing.assert_array_equal(
            full_mask(r, expected.shape[:3]), expected[..., i]
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("PatientID", "wrong"),
        ("FrameOfReferenceUID", "1.2.3.4"),
        ("StudyInstanceUID", "1.2.3.5"),
        ("SegmentationType", "FRACTIONAL"),
    ],
)
def test_reject_wrong_identity_and_unsupported_types(
    source, external_seg, field, value
):
    series, volume = source
    path, _, _ = external_seg
    ds = pydicom.dcmread(path)
    setattr(ds, field, value)
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError):
        read_segmentation(path, volume, series.instances)


def test_reject_non_native_grid_duplicate_and_cancel(source, external_seg):
    series, volume = source
    path, _, _ = external_seg
    original = path.read_bytes()
    ds = pydicom.dcmread(path)
    ds.SharedFunctionalGroupsSequence[0].PixelMeasuresSequence[0].PixelSpacing = [1, 1]
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError):
        read_segmentation(path, volume, series.instances)
    path.write_bytes(original)
    ds = pydicom.dcmread(path)
    ds.PerFrameFunctionalGroupsSequence[1] = ds.PerFrameFunctionalGroupsSequence[0]
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError):
        read_segmentation(path, volume, series.instances)
    with pytest.raises(InterruptedError):
        read_segmentation(path, volume, series.instances, cancelled=lambda: True)


@pytest.mark.parametrize("smooth", [False, True])
def test_freehand_to_native_slice_is_manual_and_preserves_measurement(source, tmp_path, smooth):
    series, volume = source
    roi = freehand(series, volume)
    from qt_dicom_viewer.core.measurement_geometry import roi_metrics
    metrics = roi_metrics(roi.measurement.points, roi.measurement.kind, volume.modality_pixels[1],
                          row_spacing=2, column_spacing=.7, unit="HU", smooth=smooth)
    roi = replace(roi, measurement=replace(roi.measurement, smooth=smooth, metrics=metrics))
    before = roi.measurement
    record, evaluation = roi_to_mask(volume, roi.measurement, roi.frame)
    mask = full_mask(record, volume.modality_pixels.shape)
    assert not mask[0].any() and not mask[2:].any() and mask[1].any()
    assert evaluation.metrics["count"] == roi.measurement.metrics.pixel_count
    assert evaluation.threshold is None and roi.measurement == before
    output, _ = write_results(
        tmp_path, segments=[SegmentResult(record, evaluation, series.instances)]
    )
    assert (
        pydicom.dcmread(output / "SEG-001.dcm").SegmentSequence[0].SegmentAlgorithmType
        == "MANUAL"
    )
    shifted = replace(
        roi,
        frame=(
            *roi.frame[:5],
            (
                *roi.frame[5][:2],
                *np.array(roi.frame[5][2:5])
                + 0.2 * np.cross(roi.frame[5][5:8], roi.frame[5][8:11]),
                *roi.frame[5][5:],
            ),
        ),
    )
    shifted_record, _ = roi_to_mask(volume, shifted.measurement, shifted.frame)
    np.testing.assert_array_equal(full_mask(shifted_record, mask.shape), mask)


def test_enhanced_temporal_frames_do_not_import_into_another_phase(tmp_path):
    from qt_dicom_viewer.core.mpr_voi import VoiRegion, evaluate_voi

    _, snapshot = save_and_scan(tmp_path, enhanced_dataset())
    series = snapshot.series[0]
    volume = VolumeManager().get_or_build(series)
    g = volume.geometry
    region = VoiRegion(
        tuple(g.center_patient),
        tuple(
            map(
                tuple,
                (
                    g.column_index_direction_patient,
                    g.row_index_direction_patient,
                    g.slice_index_direction_patient,
                ),
            )
        ),
        (100, 100, 100),
    )
    evaluation = evaluate_voi(volume, region, threshold=None)
    record = dict(
        id="temporal",
        series=series.series_instance_uid,
        name="Temporal",
        kind="voi",
        unitLabel="MR",
        color="#ed55ed",
    )
    output, _ = write_results(
        tmp_path,
        segments=[SegmentResult(record, evaluation, series.instances)],
        report=False,
    )
    records, _ = read_segmentation(
        output / "SEG-001.dcm", volume, series.instances, phase=None
    )
    assert records[0]["phase"] is None
    other = snapshot.series[1]
    other_volume = VolumeManager().get_or_build(other)
    with pytest.raises(ValueError):
        read_segmentation(
            output / "SEG-001.dcm", other_volume, other.instances, phase=None
        )


@pytest.mark.parametrize("xaxis,yaxis", [(2, 1), (2, 0), (1, 0)])
@pytest.mark.parametrize("flip", [False, True])
def test_roi_native_axes_flip_and_display_sampling(source, xaxis, yaxis, flip):
    from qt_dicom_viewer.model import ImagePoint

    series, volume = source
    g = volume.geometry
    steps = g.voxel_to_patient[:3, :3]
    spacing = np.linalg.norm(steps, axis=0)
    origin_index = np.zeros(3)
    normal = next(i for i in range(3) if i not in (xaxis, yaxis))
    origin_index[normal] = 1
    origin_index[xaxis] = 3 if flip else 0
    origin = (g.voxel_to_patient @ [*origin_index, 1])[:3]
    u = steps[:, xaxis] / spacing[xaxis] * (-1 if flip else 1)
    v = steps[:, yaxis] / spacing[yaxis]
    # Half-spacing display: the square covers three native center samples.
    roi = freehand(series, volume)
    points = tuple(ImagePoint(x, y) for x, y in [(2, 2), (6, 2), (6, 6), (2, 6)])
    measurement = replace(roi.measurement, points=points)
    frame = (*roi.frame[:5], (spacing[yaxis] / 2, spacing[xaxis] / 2, *origin, *u, *v))
    record, _ = roi_to_mask(volume, measurement, frame)
    mask = full_mask(record, volume.modality_pixels.shape)
    expected = np.zeros_like(mask)
    slices = [slice(1, 4)] * 3
    slices[normal] = slice(1, 2)
    if flip:
        slices[xaxis] = slice(0, 3)
    expected[tuple(slices)] = True
    np.testing.assert_array_equal(mask, expected)


def test_roi_rejects_oblique_and_projection_provenance(source):
    series, volume = source
    roi = freehand(series, volume)
    pose = np.array(roi.frame[5])
    u, v = pose[5:8].copy(), pose[8:11].copy()
    pose[5:8], pose[8:11] = (u + v) / np.sqrt(2), (v - u) / np.sqrt(2)
    with pytest.raises(ValueError):
        roi_to_mask(volume, roi.measurement, (*roi.frame[:5], tuple(pose)))
    with pytest.raises(ValueError):
        roi_to_mask(volume, roi.measurement, (*roi.frame, ("max", 10)))


def test_roi_phase_context_uses_source_identifier_and_preserves_workspace_index(source):
    series, volume = source
    roi = freehand(series, volume)
    record, evaluation = roi_to_mask(volume, roi.measurement,
        (*roi.frame, ("phase", 7)), phase=1, source_phase_identifier=7)
    assert record["phase"] == 1
    assert evaluation.metrics["count"] == roi.measurement.metrics.pixel_count


@pytest.mark.parametrize('context', [("phase", 8), ("projection", "max", 10, "phase", 7), ("phase", 7, "unknown")])
def test_roi_rejects_stale_or_projected_phase_context(source, context):
    series, volume = source
    roi = freehand(series, volume)
    with pytest.raises(ValueError):
        roi_to_mask(volume, roi.measurement, (*roi.frame, context), phase=1, source_phase_identifier=7)
