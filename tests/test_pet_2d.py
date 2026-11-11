from dataclasses import replace
from math import exp, log
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    ExplicitVRLittleEndian,
    PositronEmissionTomographyImageStorage,
    generate_uid,
)

from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.dicom_scanner import (
    _build_series_record,
    _read_instance,
)
from voxplane.core.measurement_geometry import roi_metrics
from voxplane.core.pet import (
    ENHANCED_PET_IMAGE_STORAGE_UID,
    PET_IMAGE_STORAGE_UID,
    UnsupportedPetSeriesError,
    pet_2d_support_error,
    validate_pet_2d_series,
)
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import (
    DicomFolderScanSnapshot,
    FrameDisplayMeta,
    ImageGeometryMeta,
    ImagePoint,
    InstanceDisplayMeta,
    MeasurementKind,
    PixelSpacing,
    PixelUnitOption,
    PixelValueMeta,
    RenderFailure,
    RoiMeasurement,
    RoiMetrics,
    SeriesDisplayMeta,
    StackRenderResult,
    StackRenderRequest,
    TabType,
    TwoDViewType,
    ViewportConfig,
    WindowLevel,
)
from voxplane.application.series_catalog import SeriesCatalog
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.stack_viewport_controller import (
    StackViewportController,
)
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker
from shiboken6 import delete
from test_measurement_qml import _visual_children, qt_app


def _pet_dataset(
    pixels: np.ndarray | None = None,
    *,
    units: str = "BQML",
) -> FileDataset:
    sop_instance_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = (
        PositronEmissionTomographyImageStorage
    )
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid

    source = np.asarray(
        [[0, 1000], [2000, 3000]] if pixels is None else pixels,
        dtype=np.uint16,
    )
    dataset = FileDataset(
        None,
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128,
    )
    dataset.PatientName = "PET Patient"
    dataset.PatientID = "PET001"
    dataset.PatientWeight = 70
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.SOPClassUID = PositronEmissionTomographyImageStorage
    dataset.SOPInstanceUID = sop_instance_uid
    dataset.Modality = "PT"
    dataset.SeriesType = ["STATIC", "IMAGE"]
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = 1
    dataset.Rows, dataset.Columns = source.shape
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 0
    dataset.PixelData = source.tobytes()
    dataset.RescaleSlope = 1
    dataset.RescaleIntercept = 0
    dataset.Units = units
    dataset.CorrectedImage = ["ATTN", "DECY"]
    dataset.DecayCorrection = "START"
    dataset.AcquisitionDateTime = "20240101130000"
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.ImagePositionPatient = [0, 0, 0]
    dataset.PixelSpacing = [2, 2]

    radiopharmaceutical = Dataset()
    radiopharmaceutical.Radiopharmaceutical = "F-18 FDG"
    radiopharmaceutical.RadiopharmaceuticalStartDateTime = (
        "20240101120000"
    )
    radiopharmaceutical.RadionuclideTotalDose = 70_000_000
    radiopharmaceutical.RadionuclideHalfLife = 3600
    dataset.RadiopharmaceuticalInformationSequence = Sequence(
        [radiopharmaceutical]
    )
    return dataset


def _write_dataset(dataset: FileDataset, path: Path) -> Path:
    dataset.save_as(path, enforce_file_format=True)
    return path


def _pet_viewport() -> tuple[StackViewportController, ToolController]:
    series_meta = SeriesDisplayMeta(
        patient_name="PET Patient",
        patient_id="PET001",
        study_description="Oncology",
        series_description="Static PET",
        modality="PT",
        series_uid="pet-series",
    )
    tool_controller = ToolController(
        tab_type=TabType.TWO_D,
        modality="PT",
    )
    controller = StackViewportController(
        viewport_config=ViewportConfig(
            viewport_id="pet-viewport",
            tab_id="pet-tab",
            viewport_type=TwoDViewType.STACK,
            series_uid="pet-series",
            series_meta=series_meta,
        ),
        tool_controller=tool_controller,
    )
    return controller, tool_controller


def _pet_render_result(
    *,
    value_meta: PixelValueMeta | None = None,
) -> StackRenderResult:
    unit_options = (
        PixelUnitOption(
            unit_id="source",
            label="Source (BQML)",
            unit="Bq/ml",
            scale_from_source=1.0,
        ),
        PixelUnitOption(
            unit_id="kbqml",
            label="kBq/ml",
            unit="kBq/ml",
            scale_from_source=0.001,
        ),
        PixelUnitOption(
            unit_id="suvbw",
            label="g/ml (SUVbw)",
            unit="SUVbw",
            scale_from_source=0.002,
        ),
    )
    return StackRenderResult(
        response_id="pet-response",
        viewport_id="pet-viewport",
        series_uid="pet-series",
        view_type=TwoDViewType.STACK,
        image=np.zeros((2, 2), dtype=np.uint8),
        modality_pixel=np.asarray([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32),
        frame_meta=FrameDisplayMeta(
            slice_index=0,
            slice_count=2,
            window=WindowLevel(center=2.5, width=5.0),
            inverted=False,
            instance_meta=InstanceDisplayMeta(
                instance_number=1,
                sop_instance_uid="pet-sop",
                manufacturer="Example",
                kvp=120,
                tube_current_ma=200,
                slice_thickness=2,
                rows=2,
                columns=2,
                pixel_spacing=(2, 2),
                image_position=(0, 0, 0),
                slice_location=0,
                radiopharmaceutical="F-18 FDG",
                pet_units="BQML",
                decay_correction="START",
                corrected_image=("ATTN", "DECY"),
            ),
            geometry=ImageGeometryMeta(
                rows=2,
                columns=2,
                pixel_spacing=PixelSpacing(row=2, column=2),
                image_position_patient=(0, 0, 0),
                image_orientation_patient=(1, 0, 0, 0, 1, 0),
            ),
            pixel_value_meta=value_meta
            or PixelValueMeta(
                unit="SUVbw",
                suv_type="BW",
                source_unit="BQML",
                quantification="derived",
                unit_id="suvbw",
                scale_from_source=0.002,
                unit_options=unit_options,
            ),
        ),
    )


def test_scanner_extracts_supported_classic_pet_metadata(tmp_path: Path) -> None:
    dataset = _pet_dataset(units="GML")
    dataset.SUVType = "BSA"
    path = _write_dataset(dataset, tmp_path / "pet.dcm")

    instance = _read_instance(path)

    assert instance is not None
    assert instance.modality == "PT"
    assert instance.sop_class_uid == PET_IMAGE_STORAGE_UID
    assert instance.number_of_frames == 1
    assert instance.pet_series_type == ("STATIC", "IMAGE")
    assert instance.pet_units == "GML"
    assert instance.pet_suv_type == "BSA"
    assert instance.pet_corrected_image == ("ATTN", "DECY")
    assert instance.pet_decay_correction == "START"
    assert instance.pet_2d_supported is True
    assert instance.pet_2d_support_error == ""

    series = _build_series_record([instance])
    assert series.pet_2d_supported is True
    validate_pet_2d_series(series)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"series_type": ("DYNAMIC", "IMAGE")}, "DYNAMIC"),
        ({"series_type": ("GATED", "IMAGE")}, "GATED"),
        ({"series_type": ("STATIC", "REPROJECTION")}, "REPROJECTION"),
        ({"sop_class_uid": ENHANCED_PET_IMAGE_STORAGE_UID}, "Enhanced"),
        ({"number_of_frames": 10}, "多帧"),
        ({"photometric_interpretation": "MONOCHROME1"}, "MONOCHROME2"),
    ],
)
def test_pet_support_check_rejects_unsupported_variants(
    changes: dict,
    message: str,
) -> None:
    error = pet_2d_support_error(
        modality="PT",
        sop_class_uid=changes.get("sop_class_uid", PET_IMAGE_STORAGE_UID),
        number_of_frames=changes.get("number_of_frames", 1),
        photometric_interpretation=changes.get(
            "photometric_interpretation",
            "MONOCHROME2",
        ),
        series_type=changes.get("series_type", ("STATIC", "IMAGE")),
    )

    assert message in error


def test_runtime_validation_rejects_dynamic_pet(tmp_path: Path) -> None:
    path = _write_dataset(_pet_dataset(), tmp_path / "pet.dcm")
    instance = _read_instance(path)
    assert instance is not None
    dynamic = replace(instance, pet_series_type=("DYNAMIC", "IMAGE"))
    series = replace(
        _build_series_record([dynamic]),
        instances=(dynamic,),
        pet_series_type=dynamic.pet_series_type,
    )

    with pytest.raises(UnsupportedPetSeriesError, match="DYNAMIC"):
        validate_pet_2d_series(series)


@pytest.mark.parametrize(
    ("series_type", "expect_success", "message"),
    [
        (("STATIC", "IMAGE"), True, ""),
        (("WHOLE BODY", "IMAGE"), True, ""),
        (("DYNAMIC", "IMAGE"), False, "DYNAMIC"),
    ],
)
def test_scanner_to_render_worker_pet_integration(
    tmp_path: Path,
    series_type: tuple[str, str],
    expect_success: bool,
    message: str,
) -> None:
    dataset = _pet_dataset()
    dataset.SeriesType = list(series_type)
    path = _write_dataset(dataset, tmp_path / "pet.dcm")
    instance = _read_instance(path)
    assert instance is not None
    series = _build_series_record([instance])
    catalog = SeriesCatalog()
    catalog.update(
        DicomFolderScanSnapshot(
            folder=tmp_path,
            total_file_count=1,
            dicom_file_count=1,
            skipped_file_count=0,
            series=[series],
        )
    )
    worker = DicomRenderWorker(catalog, VolumeManager())
    results: list[StackRenderResult] = []
    failures: list[RenderFailure] = []
    worker.render_finished.connect(results.append)
    worker.render_failed.connect(failures.append)

    worker.handleRenderRequest(
        StackRenderRequest(
            request_id="pet-request",
            viewport_id="pet-viewport",
            series_uid=series.series_instance_uid,
            slice_index=0,
            window=None,
            inverted=False,
        )
    )

    if expect_success:
        assert failures == []
        assert len(results) == 1
        assert results[0].frame_meta.pixel_value_meta.unit == "SUVbw"
    else:
        assert results == []
        assert len(failures) == 1
        assert message in str(failures[0].error)


def test_gml_is_exposed_as_existing_suv_and_defaults_to_suvbw() -> None:
    dataset = _pet_dataset(
        np.asarray([[0, 1], [5, 10]], dtype=np.uint16),
        units="GML",
    )

    result = DicomLoader().load_dataset(dataset, None, False)

    assert result.pixel_value_meta.unit == "SUVbw"
    assert result.pixel_value_meta.suv_type == "BW"
    assert result.pixel_value_meta.source_unit == "GML"
    assert result.pixel_value_meta.quantification == "native"
    assert result.pixel_value_meta.unit_options[0].label == "g/ml (SUVbw)"
    assert result.window == WindowLevel(center=2.5, width=5.0)
    np.testing.assert_allclose(result.modality_pixel, [[0, 1], [5, 10]])


@pytest.mark.parametrize(
    ("suv_type", "unit"),
    [("BSA", "SUVbsa"), ("LBM", "SUVlbm"), ("IBW", "SUVibw")],
)
def test_gml_preserves_non_bodyweight_suv_type(
    suv_type: str,
    unit: str,
) -> None:
    dataset = _pet_dataset(units="GML")
    dataset.SUVType = suv_type

    result = DicomLoader().load_dataset(dataset, None, False)

    assert result.pixel_value_meta.unit == unit
    assert result.pixel_value_meta.suv_type == suv_type


def test_bqml_start_derives_suvbw_with_decay_corrected_dose() -> None:
    dataset = _pet_dataset()
    dataset.WindowCenter = 2500
    dataset.WindowWidth = 5000

    result = DicomLoader().load_dataset(dataset, None, False)

    expected_scale = 70_000 / (
        70_000_000 * exp(-log(2) * 3600 / 3600)
    )
    assert expected_scale == pytest.approx(0.002)
    np.testing.assert_allclose(
        result.modality_pixel,
        np.asarray([[0, 2], [4, 6]], dtype=np.float32),
    )
    assert result.pixel_value_meta.quantification == "derived"
    assert result.pixel_value_meta.unit == "SUVbw"
    assert result.window == WindowLevel(center=5, width=10)


def test_bqml_admin_uses_original_administered_dose() -> None:
    dataset = _pet_dataset()
    dataset.DecayCorrection = "ADMIN"

    result = DicomLoader().load_dataset(dataset, None, False)

    np.testing.assert_allclose(
        result.modality_pixel,
        np.asarray([[0, 1], [2, 3]], dtype=np.float32),
    )
    assert result.pixel_value_meta.unit == "SUVbw"


def test_bqml_units_can_switch_between_source_kbq_and_suvbw() -> None:
    dataset = _pet_dataset()
    loader = DicomLoader()

    source = loader.load_dataset(
        dataset,
        None,
        False,
        preferred_unit="source",
    )
    kbq = loader.load_dataset(
        dataset,
        None,
        False,
        preferred_unit="kbqml",
    )
    suv = loader.load_dataset(
        dataset,
        None,
        False,
        preferred_unit="suvbw",
    )

    assert source.pixel_value_meta.unit == "Bq/ml"
    assert source.pixel_value_meta.unit_id == "source"
    assert kbq.pixel_value_meta.unit == "kBq/ml"
    assert kbq.pixel_value_meta.unit_id == "kbqml"
    assert suv.pixel_value_meta.unit == "SUVbw"
    assert suv.pixel_value_meta.unit_id == "suvbw"
    assert [option.available for option in suv.pixel_value_meta.unit_options] == [
        True,
        True,
        True,
    ]
    np.testing.assert_allclose(source.modality_pixel, [[0, 1000], [2000, 3000]])
    np.testing.assert_allclose(kbq.modality_pixel, [[0, 1], [2, 3]])
    np.testing.assert_allclose(suv.modality_pixel, [[0, 2], [4, 6]])


def test_legacy_times_handle_injection_before_midnight() -> None:
    dataset = _pet_dataset()
    del dataset.AcquisitionDateTime
    dataset.AcquisitionDate = "20240102"
    dataset.AcquisitionTime = "003000"
    item = dataset.RadiopharmaceuticalInformationSequence[0]
    del item.RadiopharmaceuticalStartDateTime
    item.RadiopharmaceuticalStartTime = "233000"

    result = DicomLoader().load_dataset(dataset, None, False)

    np.testing.assert_allclose(
        result.modality_pixel,
        np.asarray([[0, 2], [4, 6]], dtype=np.float32),
    )


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("weight", "Patient Weight"),
        ("dose", "Total Dose"),
        ("half_life", "Half Life"),
        ("administration_time", "给药日期时间"),
        ("acquisition_time", "采集日期时间"),
        ("corrections", "校正标记"),
        ("decay_correction", "Decay Correction"),
    ],
)
def test_bqml_missing_quantification_metadata_falls_back_without_fake_suv(
    missing: str,
    message: str,
) -> None:
    dataset = _pet_dataset()
    item = dataset.RadiopharmaceuticalInformationSequence[0]
    if missing == "weight":
        del dataset.PatientWeight
    elif missing == "dose":
        del item.RadionuclideTotalDose
    elif missing == "half_life":
        del item.RadionuclideHalfLife
    elif missing == "administration_time":
        del item.RadiopharmaceuticalStartDateTime
    elif missing == "acquisition_time":
        del dataset.AcquisitionDateTime
    elif missing == "corrections":
        dataset.CorrectedImage = ["ATTN"]
    elif missing == "decay_correction":
        dataset.DecayCorrection = "NONE"

    result = DicomLoader().load_dataset(dataset, None, False)

    assert result.pixel_value_meta.unit == "Bq/ml"
    assert result.pixel_value_meta.quantification == "unavailable"
    assert message in (result.pixel_value_meta.warning or "")
    assert result.pixel_value_meta.unit_options[-1].available is False
    np.testing.assert_allclose(
        result.modality_pixel,
        np.asarray([[0, 1000], [2000, 3000]], dtype=np.float32),
    )


def test_bqml_ambiguous_radiopharmaceutical_sequence_falls_back() -> None:
    dataset = _pet_dataset()
    item = dataset.RadiopharmaceuticalInformationSequence[0]
    dataset.RadiopharmaceuticalInformationSequence = Sequence([item, item])

    result = DicomLoader().load_dataset(dataset, None, False)

    assert result.pixel_value_meta.quantification == "unavailable"
    assert "不唯一" in (result.pixel_value_meta.warning or "")


def test_rescale_and_padding_are_applied_before_pet_quantification_and_roi() -> None:
    dataset = _pet_dataset(
        np.asarray([[0, 1], [2, 3]], dtype=np.uint16),
        units="GML",
    )
    dataset.RescaleSlope = 2
    dataset.RescaleIntercept = 10
    dataset.PixelPaddingValue = 0

    first = DicomLoader().load_dataset(dataset, None, False)
    dataset.RescaleSlope = 3
    second = DicomLoader().load_dataset(dataset, None, False)

    assert np.isnan(first.modality_pixel[0, 0])
    np.testing.assert_allclose(
        first.modality_pixel[~np.isnan(first.modality_pixel)],
        [12, 14, 16],
    )
    np.testing.assert_allclose(
        second.modality_pixel[~np.isnan(second.modality_pixel)],
        [13, 16, 19],
    )
    metrics = roi_metrics(
        [ImagePoint(0, 0), ImagePoint(1, 1)],
        MeasurementKind.RECT,
        first.modality_pixel,
        row_spacing=1,
        column_spacing=1,
        unit="SUVbw",
    )
    assert metrics.pixel_count == 3
    assert metrics.mean == pytest.approx(14)
    assert metrics.unit == "SUVbw"


def test_native_pet_percentile_window_is_reused_on_later_frames() -> None:
    first_dataset = _pet_dataset(
        np.arange(100, dtype=np.uint16).reshape(10, 10),
        units="CNTS",
    )
    second_dataset = _pet_dataset(
        np.arange(1000, 1100, dtype=np.uint16).reshape(10, 10),
        units="CNTS",
    )
    loader = DicomLoader()

    first = loader.load_dataset(first_dataset, None, False)
    second = loader.load_dataset(second_dataset, first.window, False)

    assert first.pixel_value_meta.unit == "counts"
    assert first.window != WindowLevel(center=40, width=400)
    assert second.window == first.window


def test_all_padding_native_pet_keeps_zero_based_intensity_range() -> None:
    dataset = _pet_dataset(
        np.zeros((2, 2), dtype=np.uint16),
        units="CNTS",
    )
    dataset.PixelPaddingValue = 0

    result = DicomLoader().load_dataset(dataset, None, False)

    assert np.isnan(result.modality_pixel).all()
    assert result.window == WindowLevel(center=0.5, width=1.0)


def test_pet_tools_presets_cursor_roi_and_overlay_are_modality_aware() -> None:
    controller, tools = _pet_viewport()
    controller.handleRenderResult(_pet_render_result())

    assert all(item["toolType"] != "service" for item in tools.tools)
    assert tools.activeToolLabel == "显示映射"
    assert tools.windowPresets == []
    assert controller.windowPresets == []
    assert controller._window_level_operation._config.minimum_width == 0.01
    assert controller._window_level_operation._config.fixed_lower_bound == 0
    assert controller.petDisplayUpper == 5
    assert controller.petControlUpper == 30
    assert controller.petActiveUnitId == "suvbw"
    assert [option["label"] for option in controller.petUnitOptions] == [
        "Source (BQML)",
        "kBq/ml",
        "g/ml (SUVbw)",
    ]

    controller.cursorController.updatePosition(1, 1, 3.25)
    assert controller.cursorController.cursorInfo == {
        "inside": True,
        "x": "1",
        "y": "1",
        "value": "3.25",
        "unit": "SUVbw",
        "label": "PET",
    }

    tools.activateTool("measure")
    tools.selectInteraction("measure:rect")
    context = controller._measurement_context(6, 6)
    assert context is not None
    assert context.pixel_unit == "SUVbw"

    overlay = controller.overlayInfo
    assert overlay["kvp"] == ""
    assert overlay["tubeCurrentMa"] == ""
    assert overlay["radiopharmaceutical"] == "F-18 FDG"
    assert overlay["petUnits"] == "BQML"
    assert overlay["pixelUnit"] == "SUVbw"
    assert overlay["suvType"] == "BW"
    assert overlay["decayCorrection"] == "START"
    assert overlay["correctedImage"] == "ATTN/DECY"
    assert overlay["windowCenter"] == "2.5"
    assert overlay["petDisplayLower"] == "0"
    assert overlay["petDisplayUpper"] == "5"


def test_pet_display_upper_and_unit_switch_drive_render_requests() -> None:
    controller, _ = _pet_viewport()
    initial = _pet_render_result()
    controller.handleRenderResult(initial)
    requests: list[StackRenderRequest] = []
    controller.renderRequested.connect(requests.append)

    controller.setPetDisplayUpper(2.5)

    assert controller.petDisplayUpper == 2.5
    assert requests[-1].window == WindowLevel(center=1.25, width=2.5)
    assert requests[-1].value_unit == "suvbw"

    controller.measurementController._measurements["pet-roi"] = RoiMeasurement(
        measurement_id="pet-roi",
        series_uid="pet-series",
        sop_instance_uid="pet-sop",
        slice_index=0,
        kind=MeasurementKind.RECT,
        points=(ImagePoint(0, 0), ImagePoint(1, 1)),
        metrics=RoiMetrics(
            pixel_count=4,
            mean=2.0,
            std=1.0,
            minimum=1.0,
            maximum=4.0,
            unit="SUVbw",
        ),
    )

    controller.setPetUnit("kbqml")

    assert controller.petUnitPending
    assert controller.petActiveUnitId == "suvbw"
    assert controller.petDisplayUpper == pytest.approx(5.0)  # last committed image
    assert controller.petControlUpper == pytest.approx(30)
    assert requests[-1].value_unit == "kbqml"
    assert requests[-1].window == WindowLevel(center=0.625, width=1.25)
    converted_roi = controller.measurementController.committed_measurements[0]
    assert isinstance(converted_roi, RoiMeasurement)
    assert converted_roi.metrics.mean == 2.0
    assert converted_roi.metrics.unit == "SUVbw"
    controller.measurementController._measurement_frames["pet-roi"] = controller.measurementController.frame_key

    options = initial.frame_meta.pixel_value_meta.unit_options
    kbq_result = replace(
        initial,
        response_id=requests[-1].request_id,
        modality_pixel=np.asarray(
            [[0.5, 1.0], [1.5, np.nan]],
            dtype=np.float32,
        ),
        frame_meta=replace(
            initial.frame_meta,
            window=WindowLevel(center=0.625, width=1.25),
            pixel_value_meta=PixelValueMeta(
                unit="kBq/ml",
                source_unit="BQML",
                quantification="native",
                unit_id="kbqml",
                scale_from_source=0.001,
                unit_options=options,
            ),
        ),
    )
    controller.handleRenderResult(kbq_result)
    assert not controller.petUnitPending
    assert controller.petActiveUnitId == "kbqml"
    assert controller.petDisplayUpper == pytest.approx(1.25)
    assert controller.petControlUpperOptions == [2.5, 5., 10., 15., 20.]
    assert controller.measurementController.committed_measurements[0].metrics.mean == 1.
    assert controller.measurementController.committed_measurements[0].metrics.unit == "kBq/ml"
    controller.cursorController.updatePosition(1, 1, 1.5)
    assert controller.cursorController.cursorInfo["unit"] == "kBq/ml"

    controller.setPetControlUpper(1.0)
    assert controller.petControlUpper == 1.0
    assert controller.petDisplayUpper == 1.0
    assert requests[-1].window == WindowLevel(center=0.5, width=1.0)

    controller.resetPetDisplay()
    assert controller.petUnitPending
    controller.handleRenderResult(replace(initial, response_id=requests[-1].request_id))
    assert controller.petActiveUnitId == "suvbw"
    assert controller.petDisplayUpper == 5
    assert controller.petControlUpper == 30
    assert requests[-1].value_unit == "suvbw"
    reset_roi = controller.measurementController.committed_measurements[0]
    assert isinstance(reset_roi, RoiMeasurement)
    assert reset_roi.metrics.mean == 2.0
    assert reset_roi.metrics.unit == "SUVbw"


def test_non_suv_pet_uses_intensity_range_without_window_presets() -> None:
    controller, _ = _pet_viewport()
    result = _pet_render_result(
        value_meta=PixelValueMeta(
            unit="Bq/ml",
            source_unit="BQML",
            quantification="unavailable",
            warning="缺少体重",
        )
    )

    controller.handleRenderResult(result)

    assert controller.windowPresets == []
    assert controller.overlayInfo["quantificationWarning"] == "缺少体重"
    assert controller.quantificationWarning == "缺少体重"


def test_pet_2d_render_failure_is_exposed_to_viewport() -> None:
    controller, _ = _pet_viewport()

    controller.handleRenderFailure(
        RenderFailure(
            request_id="request",
            viewport_id="pet-viewport",
            error=UnsupportedPetSeriesError("暂不支持 DYNAMIC PET"),
        )
    )

    assert controller.loadState == "error"
    assert controller.errorMessage == "暂不支持 DYNAMIC PET"


def test_pet_qml_uses_intensity_panel_without_wl_ww(qt_app, tmp_path) -> None:
    controller, tools = _pet_viewport()
    controller.handleRenderResult(_pet_render_result())
    requests: list[StackRenderRequest] = []
    controller.renderRequested.connect(requests.append)
    view = QQuickView()
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(360, 720)
    warnings: list[str] = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "toolController": tools,
        "toolVisible": True,
        "viewportController": controller,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/voxplane/qml/sections/RightPanel.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(80)
    try:
        items = list(_visual_children(view.rootObject()))
        assert any(
            item.objectName() == "petIntensityPanel" and item.isVisible()
            for item in items
        )
        assert not any(
            item.isVisible() and item.property("text") in {"WL", "WW"}
            for item in items
        )
        kbq_buttons = [
            item
            for item in items
            if item.objectName() == "petUnit-kbqml"
        ]
        assert kbq_buttons, [
            (item.objectName(), item.property("text"), item.isVisible())
            for item in items
            if item.objectName() or item.property("text")
        ]
        kbq_button = kbq_buttons[0]
        center = kbq_button.mapToScene(
            QPointF(kbq_button.width() / 2, kbq_button.height() / 2)
        ).toPoint()
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, center)
        QTest.qWait(40)
        assert controller.petUnitPending
        assert controller.petActiveUnitId == "suvbw"
        assert requests[-1].value_unit == "kbqml"
        assert not warnings, warnings
        preview = tmp_path / "pet-intensity-panel.png"
        assert view.grabWindow().save(str(preview))
        print(f"QML preview: {preview}")
    finally:
        view.hide()
        delete(view)


def test_pet_qml_uses_pet_specific_corner_information(qt_app, tmp_path) -> None:
    controller, _ = _pet_viewport()
    result = _pet_render_result()
    controller.handleRenderResult(result)
    provider = DicomImageProvider()
    provider.set_array("pet-viewport", result.image)
    view = QQuickView()
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(720, 520)
    view.engine().addImageProvider("dicom", provider)
    warnings: list[str] = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "viewportController": controller,
        "hasTabs": True,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/voxplane/qml/sections/center/viewportArea/Viewport.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(80)
    try:
        texts = [
            str(item.property("text"))
            for item in _visual_children(view.rootObject())
            if item.isVisible() and item.property("text")
        ]
        combined = "\n".join(texts)
        assert "PET Range: 0 – 5 SUVbw" in combined
        assert "Tracer: F-18 FDG" in combined
        assert "Correction: ATTN/DECY · START" in combined
        assert "WL:" not in combined
        assert "WW:" not in combined
        assert not warnings, warnings
        preview = tmp_path / "pet-corner-overlay.png"
        assert view.grabWindow().save(str(preview))
        print(f"QML preview: {preview}")
    finally:
        view.hide()
        delete(view)
