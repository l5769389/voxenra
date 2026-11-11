from dataclasses import replace
import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
import highdicom as hd

from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.volume_manager import VolumeManager
from voxplane.core.dicom_results import (
    SegmentResult,
    PlanarResult,
    write_results,
    tracking_uid,
)
from voxplane.core.mpr_voi import VoiRegion, evaluate_voi
from voxplane.core.measurement_geometry import roi_metrics
from voxplane.model import ImagePoint, MeasurementKind
from voxplane.model.measure import RoiMeasurement
from test_enhanced_mr import enhanced_dataset, save_and_scan


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    angle = np.pi / 6
    u, v = np.array([1, 0, 0]), np.array([0, np.cos(angle), np.sin(angle)])
    n = np.cross(u, v)
    for k in [2, 0, 3, 1]:
        uid = generate_uid()
        fm = FileMetaDataset()
        fm.MediaStorageSOPClassUID = CTImageStorage
        fm.MediaStorageSOPInstanceUID = uid
        fm.TransferSyntaxUID = ExplicitVRLittleEndian
        d = FileDataset(
            str(folder / f"{3 - k}.dcm"), {}, file_meta=fm, preamble=b"\0" * 128
        )
        for key, value in dict(
            SOPClassUID=CTImageStorage,
            SOPInstanceUID=uid,
            StudyInstanceUID=study,
            SeriesInstanceUID=series,
            FrameOfReferenceUID=frame,
            PatientID="TEST",
            PatientName="测试^病人",
            SpecificCharacterSet="ISO_IR 192",
            PatientBirthDate="",
            PatientSex="",
            AccessionNumber="",
            StudyID="1",
            StudyDate="20260916",
            StudyTime="120000",
            Modality="CT",
            SeriesNumber=1,
            InstanceNumber=k + 1,
            Rows=9,
            Columns=11,
            PixelSpacing=[2.0, 0.7],
            SliceThickness=3.0,
            ImageOrientationPatient=[*u, *v],
            ImagePositionPatient=(np.array([10, 20, 30]) + k * 3 * n).tolist(),
            SamplesPerPixel=1,
            PhotometricInterpretation="MONOCHROME2",
            BitsAllocated=16,
            BitsStored=16,
            HighBit=15,
            PixelRepresentation=1,
            RescaleSlope=1,
            RescaleIntercept=-1000,
        ).items():
            setattr(d, key, value)
        d.PixelData = (
            np.arange(99, dtype=np.int16).reshape(9, 11) + 1100 + k
        ).tobytes()
        d.save_as(d.filename, enforce_file_format=True)
    snapshot = list(
        DicomFolderScanner().scan_files(
            list(folder.glob("*.dcm")), folder=folder, can_publish=lambda: False
        )
    )[-1]
    s = snapshot.series[0]
    vol = VolumeManager().get_or_build(s)
    return s, vol


def segmentation(series, volume, identifier="segment-one"):
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
        (5, 10, 8),
    )
    evaluation = evaluate_voi(volume, region, threshold=150)
    record = dict(
        id=identifier,
        region=region,
        series=series.series_instance_uid,
        name="测试分割",
        kind="segmentation",
        unitLabel="HU",
        color="#ffbb55",
    )
    return SegmentResult(record, evaluation, series.instances)


def freehand(series, volume):
    source = series.instances[1]
    p = (
        ImagePoint(1, 1),
        ImagePoint(7, 1),
        ImagePoint(7, 6),
        ImagePoint(4, 4),
        ImagePoint(1, 6),
    )
    metrics = roi_metrics(
        p,
        MeasurementKind.FREEHAND,
        volume.modality_pixels[1],
        row_spacing=2,
        column_spacing=0.7,
        unit="HU",
    )
    item = RoiMeasurement(
        "roi-id",
        series.series_instance_uid,
        source.sop_instance_uid,
        1,
        MeasurementKind.FREEHAND,
        p,
        metrics,
    )
    frame = (
        series.series_instance_uid,
        source.sop_instance_uid,
        1,
        9,
        11,
        (2.0, 0.7, *source.image_position_patient, *source.image_orientation_patient),
    )
    return PlanarResult(item, frame, series.instances)


def walk(dataset):
    yield dataset
    for child in dataset.get("ContentSequence", []):
        yield from walk(child)


def test_seg_roundtrip_oblique_sparse_positions_references_and_overlap(
    source, tmp_path
):
    series, volume = source
    r = segmentation(series, volume)
    before = {i.path: i.path.read_bytes() for i in series.instances}
    output, count = write_results(
        tmp_path,
        segments=[r, replace(r, record=dict(r.record, id="second"))],
        report=False,
    )
    assert count == 1
    for path in sorted(output.glob("*.dcm")):
        seg = pydicom.dcmread(path)
        assert (
            seg.SOPClassUID == pydicom.uid.SegmentationStorage
            and seg.SegmentationType == "BINARY"
        )
        assert (
            seg.BitsAllocated == 1
            and seg.FrameOfReferenceUID == series.frame_of_reference_uid
        )
        assert "ContentCreatorName" in seg
        assert (
            seg.PatientName == "测试^病人"
            and seg.SegmentSequence[0].SegmentLabel == "测试分割"
        )
        assert len(seg.SegmentSequence) == 2
        reconstructed = np.zeros((*volume.modality_pixels.shape, 2), dtype=bool)
        pixels = seg.pixel_array
        if pixels.ndim == 2:
            pixels = pixels[None]
        for image, group in zip(pixels, seg.PerFrameFunctionalGroupsSequence):
            pos = group.PlanePositionSequence[0].ImagePositionPatient
            index = volume.geometry.patient_to_voxel @ [*pos, 1]
            k = round(index[0])
            np.testing.assert_allclose(index[:3], [k, 0, 0], atol=1e-5)
            n = int(group.SegmentIdentificationSequence[0].ReferencedSegmentNumber) - 1
            reconstructed[k, :, :, n] = image
            ref = group.DerivationImageSequence[0].SourceImageSequence[0]
            assert ref.ReferencedSOPInstanceUID == series.instances[k].sop_instance_uid
        expected = np.zeros_like(reconstructed)
        o = r.evaluation.offset
        m = r.evaluation.mask
        expected[tuple(slice(a, a + b) for a, b in zip(o, m.shape))] = m[..., None]
        np.testing.assert_array_equal(reconstructed, expected)
    assert all(path.read_bytes() == data for path, data in before.items())


def test_sr_tids_numeric_units_geometry_tracking_and_seg_link(source, tmp_path):
    series, vol = source
    r = segmentation(series, vol)
    roi = freehand(series, vol)
    output, count = write_results(tmp_path, [roi], [r])
    assert count == 3
    sr = hd.sr.srread(output / "SR-001.dcm")
    planar_sr = hd.sr.srread(output / "SR-002.dcm")
    assert sr.ContentTemplateSequence[0].TemplateIdentifier == "1500"
    assert sr.VerificationFlag == "UNVERIFIED" and sr.PreliminaryFlag == "PRELIMINARY"
    assert sr.PatientName == "测试^病人"
    assert sr.SeriesDescription == "VoxPlane segmentation measurements"
    assert planar_sr.SeriesDescription == "VoxPlane planar measurements"
    assert not sr.content.get_planar_roi_measurement_groups()
    assert not planar_sr.content.get_volumetric_roi_measurement_groups()
    items = [*walk(sr), *walk(planar_sr)]
    numeric = {
        i.ConceptNameCodeSequence[0].CodeMeaning: i
        for i in items
        if i.get("ValueType") == "NUM"
    }
    assert float(
        numeric["Area"].MeasuredValueSequence[0].NumericValue
    ) == pytest.approx(roi.measurement.metrics.area_mm2)
    assert (
        numeric["Area"]
        .MeasuredValueSequence[0]
        .MeasurementUnitsCodeSequence[0]
        .CodeValue
        == "mm2"
    )
    assert float(
        numeric["Volume"].MeasuredValueSequence[0].NumericValue
    ) == pytest.approx(r.evaluation.metrics["volume"])
    region = next(i for i in items if i.get("ValueType") == "SCOORD")
    expected = np.array(
        [
            (p.column + 0.5, p.row + 0.5)
            for p in (*roi.measurement.points, roi.measurement.points[0])
        ]
    )
    np.testing.assert_allclose(np.array(region.GraphicData).reshape(-1, 2), expected)
    source = series.instances[1]
    actual = hd.spatial.ImageToReferenceTransformer(
        source.image_position_patient, source.image_orientation_patient, [2, 0.7]
    )(np.array(region.GraphicData).reshape(-1, 2))
    first = roi.measurement.points[0]
    wanted = (
        np.array(source.image_position_patient)
        + first.column * 0.7 * np.array(source.image_orientation_patient[:3])
        + first.row * 2 * np.array(source.image_orientation_patient[3:])
    )
    np.testing.assert_allclose(actual[0], wanted)
    seg = pydicom.dcmread(output / "SEG-001.dcm")
    assert any(
        i.get("ValueType") == "IMAGE"
        and i.ReferencedSOPSequence[0].ReferencedSOPInstanceUID == seg.SOPInstanceUID
        for i in items
    )
    assert any(i.get("UID") == tracking_uid(r.record["id"]) for i in items)


def test_empty_moved_and_changed_sources_fail_without_partial_folder(source, tmp_path):
    series, vol = source
    r = segmentation(series, vol)
    folder = tmp_path / "out"
    folder.mkdir()
    empty = replace(
        r, evaluation=replace(r.evaluation, mask=np.zeros_like(r.evaluation.mask))
    )
    with pytest.raises(ValueError, match="为空"):
        write_results(folder, segments=[empty])
    assert list(folder.iterdir()) == []
    moved = replace(
        r,
        evaluation=replace(
            r.evaluation, geometry=replace(vol.geometry, origin_patient=(0, 0, 0))
        ),
    )
    with pytest.raises(ValueError):
        write_results(folder, segments=[moved])
    assert list(folder.iterdir()) == []
    with pytest.raises(InterruptedError):
        write_results(folder, segments=[r], cancelled=lambda: True)
    assert list(folder.iterdir()) == []


def test_enhanced_mr_segment_uses_actual_frame_numbers(tmp_path):
    d = enhanced_dataset()
    path, snapshot = save_and_scan(tmp_path, d)
    series = snapshot.series[-1]
    volume = VolumeManager().get_or_build(series)
    r = segmentation(series, volume)
    r = replace(
        r, evaluation=replace(r.evaluation, mask=np.ones_like(r.evaluation.mask))
    )
    output, _ = write_results(tmp_path, segments=[r], report=False)
    seg = pydicom.dcmread(output / "SEG-001.dcm")
    expected = {
        tuple(i.image_position_patient): i.frame_index + 1 for i in series.instances
    }
    for group in seg.PerFrameFunctionalGroupsSequence:
        ref = group.DerivationImageSequence[0].SourceImageSequence[0]
        assert ref.ReferencedSOPInstanceUID == d.SOPInstanceUID
        assert (
            ref.ReferencedFrameNumber
            == expected[tuple(group.PlanePositionSequence[0].ImagePositionPatient)]
        )


def test_mpr_sr_uses_patient_coordinates_and_native_mismatch_is_rejected(
    source, tmp_path
):
    from voxplane.core.dicom_results import planar_group

    series, vol = source
    roi = freehand(series, vol)
    # A real reslice between source planes has no corresponding 2D SOP frame.
    pose = list(roi.frame[5])
    pose[4] += 0.75
    frame = (*roi.frame[:5], tuple(pose))
    result = replace(roi, frame=frame, is_mpr=True)
    group, _ = planar_group(result, {})
    coordinate = next(i for i in walk(group[0]) if i.get("ValueType") == "SCOORD3D")
    expected = (
        np.array(pose[2:5]) + np.array(pose[5:8]) * 0.7 + np.array(pose[8:11]) * 2
    )
    np.testing.assert_allclose(
        np.array(coordinate.GraphicData).reshape(-1, 3)[0], expected
    )
    assert coordinate.ReferencedFrameOfReferenceUID == series.frame_of_reference_uid
    with pytest.raises(ValueError):
        planar_group(replace(result, is_mpr=False), {})


@pytest.mark.parametrize("kind", ["length", "curve", "curve_tight", "angle", "rect", "ellipse"])
def test_sr_existing_measurement_types_have_units_and_readable_regions(
    source, tmp_path, kind
):
    from voxplane.model.measure import LengthMeasurement, AngleMeasurement

    series, vol = source
    roi = freehand(series, vol)
    common = dict(
        measurement_id=kind,
        series_uid=series.series_instance_uid,
        sop_instance_uid=roi.measurement.sop_instance_uid,
        slice_index=1,
    )
    p = (ImagePoint(1, 1), ImagePoint(5, 4))
    if kind == "length":
        item = LengthMeasurement(
            **common, points=p, length_mm=float(np.hypot(4 * 0.7, 3 * 2))
        )
    elif kind in ("curve", "curve_tight"):
        from voxplane.core.curve_geometry import curve_length_mm, _sample_open_curve
        from voxplane.core.freehand_roi import simple_path
        p = (*p, ImagePoint(8, 2))
        if kind == "curve_tight":
            p = tuple(ImagePoint(*v) for v in [(1,1),(5,1),(5,5),(4.95,1.05),(1,5)])
            assert not simple_path(_sample_open_curve(p,128,1.0))
        item = LengthMeasurement(**common, points=p, kind=MeasurementKind.CURVE,
                                 length_mm=curve_length_mm(p, 2, .7))
    elif kind == "angle":
        item = AngleMeasurement(**common, points=(*p, ImagePoint(7, 2)), angle=45.0)
    else:
        m = roi_metrics(
            p,
            MeasurementKind(kind),
            vol.modality_pixels[1],
            row_spacing=2,
            column_spacing=0.7,
            unit="HU",
        )
        item = RoiMeasurement(**common, kind=MeasurementKind(kind), points=p, metrics=m)
    folder, _ = write_results(tmp_path, [replace(roi, measurement=item)])
    sr = hd.sr.srread(folder / "SR-001.dcm")
    groups = sr.content.get_planar_roi_measurement_groups()
    assert len(groups) == 1 and groups[0].get_measurements()
    if kind in ("curve", "curve_tight"):
        from voxplane.core.curve_geometry import sample_curve
        expected = np.array([(p.column+.5, p.row+.5) for p in sample_curve(item.points)])
        np.testing.assert_allclose(np.asarray(groups[0].roi.GraphicData).reshape(-1, 2), expected, atol=1e-5)
        assert float(groups[0].get_measurements()[0].value) == pytest.approx(item.length_mm)
    assert groups[0].roi.graphic_type.value == (
        "ELLIPSE" if kind == "ellipse" else "POLYLINE"
    )


def test_enhanced_sr_points_reference_selected_frame(tmp_path):
    from voxplane.model.measure import LengthMeasurement

    d = enhanced_dataset()
    path, snapshot = save_and_scan(tmp_path, d)
    series = snapshot.series[-1]
    i = series.instances[1]
    measurement = LengthMeasurement(
        "line",
        series.series_instance_uid,
        i.sop_instance_uid,
        1,
        (ImagePoint(0, 0), ImagePoint(4, 0)),
        3.2,
    )
    frame = (
        series.series_instance_uid,
        i.sop_instance_uid,
        1,
        8,
        8,
        (0.8, 0.8, *i.image_position_patient, *i.image_orientation_patient),
    )
    folder, _ = write_results(
        tmp_path, [PlanarResult(measurement, frame, series.instances)]
    )
    sr = pydicom.dcmread(folder / "SR-001.dcm")
    ref = next(
        i for i in walk(sr) if i.get("ValueType") == "IMAGE"
    ).ReferencedSOPSequence[0]
    assert (
        ref.ReferencedSOPInstanceUID == d.SOPInstanceUID
        and ref.ReferencedFrameNumber == i.frame_index + 1
    )


@pytest.mark.parametrize(
    "context", [("projection", "mip", 20), ("registered", 1, 0, 0, 15)]
)
def test_projection_or_registration_origin_survives_display_reset(
    source, tmp_path, context
):
    from voxplane.core.workspace_state import dumps, loads

    series, volume = source
    result = freehand(series, volume)
    result = replace(result, frame=loads(dumps(result.frame + (context,))))
    with pytest.raises(ValueError):
        write_results(tmp_path, planar=[result])
    assert not list(tmp_path.glob("voxplane-results-*"))


@pytest.mark.parametrize(
    "unit,code",
    [
        ("SUVbw", "g/ml"),
        ("kBq/ml", "kBq/ml"),
        ("Bq/ml", "Bq/ml"),
        ("counts/s", "{counts}/s"),
        ("%", "%"),
    ],
)
def test_sr_retains_pet_numeric_values_and_ucum_units(source, tmp_path, unit, code):
    series, volume = source
    result = freehand(series, volume)
    result = replace(
        result,
        measurement=replace(
            result.measurement, metrics=replace(result.measurement.metrics, unit=unit)
        ),
    )
    output, _ = write_results(tmp_path, planar=[result])
    sr = hd.sr.srread(output / "SR-001.dcm")
    mean = next(
        i
        for i in walk(sr)
        if i.get("ValueType") == "NUM"
        and i.ConceptNameCodeSequence[0].CodeMeaning == "Mean"
    )
    numeric = mean.MeasuredValueSequence[0]
    assert float(numeric.NumericValue) == result.measurement.metrics.mean
    assert numeric.MeasurementUnitsCodeSequence[0].CodingSchemeDesignator == "UCUM"
    assert numeric.MeasurementUnitsCodeSequence[0].CodeValue == code


@pytest.mark.parametrize(
    "key,value", [("PatientID", "ANOTHER"), ("StudyInstanceUID", "1.2.3.456")]
)
def test_seg_only_rejects_inconsistent_source_identity(source, tmp_path, key, value):
    series, volume = source
    path = series.instances[0].path
    ds = pydicom.dcmread(path)
    setattr(ds, key, value)
    ds.save_as(path, enforce_file_format=True)
    with pytest.raises(ValueError):
        write_results(tmp_path, segments=[segmentation(series, volume)], report=False)
    assert not list(tmp_path.glob("voxplane-results-*"))


def test_grouped_segments_reference_matching_numbers_and_keep_overlap(source, tmp_path):
    series, volume = source
    first = segmentation(series, volume)
    second = replace(first, record=dict(first.record, id="other", name="Other"))
    output, count = write_results(tmp_path, segments=[first, second])
    assert count == 2
    seg = hd.seg.segread(output / "SEG-001.dcm")
    assert [int(d.SegmentNumber) for d in seg.SegmentSequence] == [1, 2]
    sr = hd.sr.srread(output / "SR-001.dcm")
    groups = sr.content.get_volumetric_roi_measurement_groups()
    assert len(groups) == 2
    for number, group in enumerate(groups, 1):
        refs = [
            n.ReferencedSOPSequence[0]
            for n in walk(group[0])
            if n.get("ValueType") == "IMAGE"
            and n.ReferencedSOPSequence[0].ReferencedSOPClassUID
            == pydicom.uid.SegmentationStorage
        ]
        assert len(refs) == 1
        assert refs[0].ReferencedSOPInstanceUID == seg.SOPInstanceUID
        assert refs[0].ReferencedSegmentNumber == number
        assert group.tracking_uid == seg.SegmentSequence[number - 1].TrackingUID


def test_bounded_segment_batches_have_separate_readable_reports(
    source, tmp_path, monkeypatch
):
    import voxplane.core.dicom_results as module

    series, volume = source
    monkeypatch.setattr(module, "SEG_BATCH_BYTES", volume.modality_pixels.size)
    first = segmentation(series, volume)
    output, count = write_results(
        tmp_path,
        segments=[first, replace(first, record=dict(first.record, id="other"))],
    )
    assert count == 4
    for number in (1, 2):
        seg = hd.seg.segread(output / f"SEG-{number:03}.dcm")
        sr = hd.sr.srread(output / f"SR-{number:03}.dcm")
        groups = sr.content.get_volumetric_roi_measurement_groups()
        assert len(groups) == len(seg.SegmentSequence) == 1
        refs = [
            n.ReferencedSOPSequence[0]
            for n in walk(sr)
            if n.get("ValueType") == "IMAGE"
            and n.ReferencedSOPSequence[0].ReferencedSOPClassUID
            == pydicom.uid.SegmentationStorage
        ]
        assert len(refs) == 1 and refs[0].ReferencedSOPInstanceUID == seg.SOPInstanceUID


def test_enhanced_ct_seg_export_keeps_source_phase_frames(tmp_path):
    from test_enhanced_ct import save_and_scan
    from voxplane.core.segmentation_import import read_segmentation

    _, snapshot = save_and_scan(tmp_path)
    series = snapshot.series[0]
    volume = VolumeManager().get_or_build(series)
    base = segmentation(series, volume)
    mask = np.ones(volume.modality_pixels.shape, dtype=bool)
    record = dict(
        base.record,
        mask=mask,
        mask_offset=(0, 0, 0),
        mask_affine=volume.geometry.voxel_to_patient,
    )
    # Keep valid fixed-mask bookkeeping from the mask evaluator's established schema.
    from dataclasses import replace

    evaluation = replace(base.evaluation, mask=mask, offset=(0, 0, 0), threshold=None)
    output, _ = write_results(
        tmp_path,
        segments=[replace(base, record=record, evaluation=evaluation)],
        report=False,
    )
    seg = pydicom.dcmread(output / "SEG-001.dcm")
    refs = [
        f.DerivationImageSequence[0].SourceImageSequence[0]
        for f in seg.PerFrameFunctionalGroupsSequence
    ]
    assert {int(r.ReferencedFrameNumber) for r in refs} == {
        i.frame_index + 1 for i in series.instances
    }
    records, _ = read_segmentation(output / "SEG-001.dcm", volume, series.instances)
    assert len(records) == 1 and records[0]["mask"].all()


def test_smooth_roi_sr_exports_boundary_not_control_polygon(source, tmp_path):
    from voxplane.core.freehand_roi import roi_outline
    series, volume = source
    result = freehand(series, volume)
    metrics = roi_metrics(result.measurement.points, MeasurementKind.FREEHAND,
                          volume.modality_pixels[1], row_spacing=2, column_spacing=.7,
                          unit="HU", smooth=True)
    item = replace(result.measurement, smooth=True, metrics=metrics)
    folder, _ = write_results(tmp_path, [replace(result, measurement=item)])
    sr = hd.sr.srread(folder / "SR-001.dcm")
    group = sr.content.get_planar_roi_measurement_groups()[0]
    boundary = roi_outline(item.points, True)
    expected = np.array([(p.column+.5,p.row+.5) for p in (*boundary,boundary[0])])
    actual = np.asarray(group.roi.GraphicData).reshape(-1,2)
    np.testing.assert_allclose(actual, expected, atol=1e-5)
    assert len(actual) > len(item.points)+1
