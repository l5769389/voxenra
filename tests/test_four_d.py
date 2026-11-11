from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import (
    MprFrame,
    MprPlane,
    MprRenderRequest,
    RenderFailure,
    SeriesDisplayMeta,
    TabConfig,
    TabType,
)
from voxplane.ui.controller.tab.tab_controller import TabController
from voxplane.ui.controller.viewport.image_2d.mpr_viewport_controller import (
    MprViewportController,
)
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker
from test_viewport_controller_hierarchy import _mpr_result


def _write_phase_slice(
    path: Path,
    *,
    phase_identifier: int,
    phase_count: int,
    slice_index: int,
    value: int,
) -> None:
    sop_uid = f"1.2.826.0.1.3680043.10.543.{phase_identifier}.{slice_index + 1}"
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    dataset = FileDataset(
        str(path),
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128,
    )
    dataset.PatientName = "4D Example"
    dataset.PatientID = "P4D"
    dataset.StudyInstanceUID = "1.2.826.0.1.3680043.10.543.100"
    dataset.SeriesInstanceUID = "1.2.826.0.1.3680043.10.543.200"
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.Modality = "CT"
    dataset.SeriesNumber = 4
    dataset.InstanceNumber = phase_identifier * 100 + slice_index
    dataset.TemporalPositionIdentifier = phase_identifier
    dataset.NumberOfTemporalPositions = phase_count
    dataset.NumberOfFrames = 1
    dataset.Rows = 3
    dataset.Columns = 4
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 1
    dataset.PixelSpacing = [1.0, 1.0]
    dataset.SliceThickness = 1.0
    dataset.ImagePositionPatient = [0.0, 0.0, float(slice_index)]
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.WindowCenter = 15
    dataset.WindowWidth = 40
    pixels = np.full((3, 4), value, dtype="<i2")
    dataset.PixelData = pixels.tobytes()
    dataset.save_as(path, enforce_file_format=True)


def _cross_series_four_d(
    tmp_path: Path,
    *,
    phase_count: int = 3,
    description_base: str = "MP1",
    source_keyword: str | None = None,
    source_values: tuple[int | float | str, ...] | None = None,
):
    if source_values is not None:
        assert len(source_values) == phase_count
    for phase_identifier in range(phase_count):
        phase_folder = tmp_path / description_base / f"ph{phase_identifier}"
        phase_folder.mkdir(parents=True)
        for slice_index in (1, 0):
            path = phase_folder / f"IM_{slice_index + 1:04d}.dcm"
            _write_phase_slice(
                path,
                phase_identifier=phase_identifier + 1,
                phase_count=phase_count,
                slice_index=slice_index,
                value=(phase_identifier + 1) * 10,
            )
            dataset = pydicom.dcmread(path)
            dataset.SeriesInstanceUID = (
                f"1.2.826.0.1.3680043.10.543.20{phase_identifier}"
            )
            dataset.SeriesDescription = (
                f"{description_base}_ph{phase_identifier}"
                if source_keyword is None
                else description_base
            )
            dataset.SeriesNumber = 100 + phase_identifier
            dataset.FrameOfReferenceUID = (
                "1.2.826.0.1.3680043.10.543.300"
            )
            del dataset.TemporalPositionIdentifier
            del dataset.NumberOfTemporalPositions
            if source_keyword is not None:
                value = (
                    source_values[phase_identifier]
                    if source_values is not None
                    else phase_identifier
                )
                setattr(dataset, source_keyword, value)
            dataset.save_as(path, enforce_file_format=True)

    return _scan_series(tmp_path)


def _scan_series(folder: Path):
    snapshot = None
    for snapshot in DicomFolderScanner().scan(folder):
        pass
    assert snapshot is not None
    return sorted(snapshot.series, key=lambda series: series.series_number or 0)


def _four_d_meta(phase_count: int = 3) -> SeriesDisplayMeta:
    return SeriesDisplayMeta(
        patient_name="4D Example",
        patient_id="P4D",
        study_description="Perfusion",
        series_description="Dynamic CT",
        modality="CT",
        series_uid="series-4d",
        phase_identifiers=tuple(range(1, phase_count + 1)),
        supports_four_d=True,
    )


def _finish_requests(
    tab: TabController,
    requests: list[MprRenderRequest],
    frame: MprFrame,
) -> None:
    while requests:
        request = requests.pop(0)
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        result = replace(
            _mpr_result(
                viewport,
                frame,
                request.request_id,
            ),
            phase_identifier=request.phase_identifier,
        )
        tab.handleRenderResult(result)


def _ready_four_d_tab(phase_count: int = 3):
    tab = TabController(
        TabConfig(
            "four-d-tab",
            "4D",
            TabType.FOUR_D,
            (_four_d_meta(phase_count),),
        )
    )
    requests: list[MprRenderRequest] = []
    tab.renderRequested.connect(requests.append)
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    tab.init_render()
    _finish_requests(tab, requests, frame)
    return tab, requests, frame


def test_scanner_links_multiple_series_as_one_four_d_group(
    tmp_path: Path,
) -> None:
    series_records = _cross_series_four_d(tmp_path)

    assert len(series_records) == 3
    assert all(series.supports_four_d for series in series_records)
    assert all(
        series.phase_source_keyword == "SeriesDescriptionPhaseSuffix"
        for series in series_records
    )
    assert all(series.phase_identifiers == (0, 1, 2) for series in series_records)
    assert [
        series.initial_phase_identifier for series in series_records
    ] == [0, 1, 2]
    assert [phase.dicom_file_count for phase in series_records[0].phases] == [
        2,
        2,
        2,
    ]
    assert [
        instance.image_position_patient[2]
        for instance in series_records[0].phases[0].instances
    ] == [0.0, 1.0]


def test_cross_series_four_d_opens_on_selected_series_phase(
    tmp_path: Path,
) -> None:
    selected_series = _cross_series_four_d(tmp_path)[2]
    catalog = SeriesCatalog()
    catalog._series_by_uid[selected_series.series_instance_uid] = selected_series
    meta = catalog.get_series_display_meta(selected_series.series_instance_uid)
    assert meta is not None

    tab = TabController(
        TabConfig(
            "cross-series-four-d",
            "4D",
            TabType.FOUR_D,
            (meta,),
        )
    )
    requests: list[MprRenderRequest] = []
    tab.renderRequested.connect(requests.append)
    tab.init_render()

    assert tab.currentPhaseIndex == 2
    assert len(requests) == 1
    assert requests[0].phase_identifier == 2


def test_cross_series_volume_uses_phase_series_pixels(
    tmp_path: Path,
) -> None:
    selected_series = _cross_series_four_d(tmp_path)[1]
    manager = VolumeManager()

    phase_zero = manager.get_or_build(selected_series, phase_identifier=0)
    phase_two = manager.get_or_build(selected_series, phase_identifier=2)

    np.testing.assert_allclose(phase_zero.modality_pixels, 10.0)
    np.testing.assert_allclose(phase_two.modality_pixels, 30.0)


_ALTERNATIVE_PHASE_SOURCES = (
    ("TemporalPositionIdentifier", (3, 8)),
    ("TemporalPositionIndex", (3, 8)),
    ("PhaseNumber", (2, 4)),
    ("FrameAcquisitionNumber", (11, 12)),
    (
        "NominalPercentageOfCardiacPhase",
        (0.0, 50.0),
    ),
    (
        "NominalPercentageOfRespiratoryPhase",
        (20.0, 80.0),
    ),
    (
        "RespiratoryCyclePosition",
        ("START_RESPIR", "END_RESPIR"),
    ),
    (
        "CardiacCyclePosition",
        ("END_DIASTOLE", "END_SYSTOLE"),
    ),
    (
        "TemporalPositionTimeOffset",
        (0.0, 125.5),
    ),
    ("TriggerTime", (10.0, 810.0)),
    ("ImageTriggerDelay", (15.0, 115.0)),
    ("TriggerTimeOffset", (5.0, 205.0)),
    (
        "NominalCardiacTriggerDelayTime",
        (10.0, 410.0),
    ),
    (
        "NominalCardiacTriggerTimePriorToRPeak",
        (20.0, 220.0),
    ),
    (
        "ActualCardiacTriggerTimePriorToRPeak",
        (21.0, 221.0),
    ),
    (
        "ActualCardiacTriggerDelayTime",
        (12.0, 412.0),
    ),
    (
        "NominalRespiratoryTriggerDelayTime",
        (0.0, 900.0),
    ),
    (
        "ActualRespiratoryTriggerDelayTime",
        (1.0, 901.0),
    ),
    ("FrameReferenceTime", (0.0, 1000.0)),
    ("PhaseDelay", (0, 100)),
    ("PhaseDescription", ("EARLY", "LATE")),
    ("AcquisitionNumber", (7, 8)),
    (
        "FrameAcquisitionDateTime",
        ("20260904100000", "20260904100100"),
    ),
    (
        "AcquisitionDateTime",
        ("20260904100000", "20260904100100"),
    ),
    ("AcquisitionTime", ("100000", "100100")),
    ("ContentTime", ("100000", "100100")),
)


@pytest.mark.parametrize(
    ("source_keyword", "source_values"),
    _ALTERNATIVE_PHASE_SOURCES,
)
def test_cross_series_detection_supports_common_phase_tags(
    tmp_path: Path,
    source_keyword: str,
    source_values: tuple[int | float | str, int | float | str],
) -> None:
    series_records = _cross_series_four_d(
        tmp_path,
        phase_count=2,
        source_keyword=source_keyword,
        source_values=source_values,
    )

    assert all(series.supports_four_d for series in series_records)
    assert all(
        series.phase_source_keyword == source_keyword
        for series in series_records
    )
    expected_identifiers = (
        source_values
        if all(isinstance(value, int) for value in source_values)
        else (1, 2)
    )
    assert all(
        series.phase_identifiers == expected_identifiers
        for series in series_records
    )
    assert tuple(
        series.initial_phase_identifier for series in series_records
    ) == expected_identifiers
    assert series_records[0].instances[0].phase_value(source_keyword) == (
        source_values[0]
    )


def test_phase_detection_rejects_unique_per_slice_acquisition_times(
    tmp_path: Path,
) -> None:
    _cross_series_four_d(
        tmp_path,
        phase_count=2,
        source_keyword="AcquisitionTime",
        source_values=("100000", "100100"),
    )
    path = tmp_path / "MP1" / "ph0" / "IM_0002.dcm"
    dataset = pydicom.dcmread(path)
    dataset.AcquisitionTime = "100001"
    dataset.save_as(path, enforce_file_format=True)

    assert not any(series.supports_four_d for series in _scan_series(tmp_path))


def test_phase_detection_rejects_mismatched_spatial_stacks(
    tmp_path: Path,
) -> None:
    _cross_series_four_d(tmp_path, phase_count=2)
    path = tmp_path / "MP1" / "ph1" / "IM_0002.dcm"
    dataset = pydicom.dcmread(path)
    dataset.ImagePositionPatient = [0.0, 0.0, 9.0]
    dataset.save_as(path, enforce_file_format=True)

    assert not any(series.supports_four_d for series in _scan_series(tmp_path))


def test_number_of_phases_validates_detected_phase_count(
    tmp_path: Path,
) -> None:
    _cross_series_four_d(tmp_path, phase_count=2)
    for path in tmp_path.rglob("*.dcm"):
        dataset = pydicom.dcmread(path)
        dataset.NumberOfPhases = 3
        dataset.save_as(path, enforce_file_format=True)

    assert not any(series.supports_four_d for series in _scan_series(tmp_path))


def test_cross_series_detection_rejects_multiframe_instances(
    tmp_path: Path,
) -> None:
    _cross_series_four_d(tmp_path, phase_count=2)
    for path in tmp_path.rglob("*.dcm"):
        dataset = pydicom.dcmread(path)
        dataset.NumberOfFrames = 2
        dataset.save_as(path, enforce_file_format=True)

    assert not any(series.supports_four_d for series in _scan_series(tmp_path))


def test_catalog_exposes_four_d_capability(tmp_path: Path) -> None:
    series = _cross_series_four_d(tmp_path)[0]
    catalog = SeriesCatalog()
    catalog._series_by_uid[series.series_instance_uid] = series

    meta = catalog.get_series_display_meta(series.series_instance_uid)

    assert meta is not None
    assert meta.supports_four_d
    assert meta.phase_identifiers == (0, 1, 2)
    assert meta.initial_phase_identifier == 0


def test_volume_cache_isolated_by_temporal_phase(tmp_path: Path) -> None:
    series = _cross_series_four_d(tmp_path, phase_count=2)[0]
    manager = VolumeManager()

    first = manager.get_or_build(series, phase_identifier=0)
    second = manager.get_or_build(series, phase_identifier=1)

    assert first is manager.get_or_build(series, phase_identifier=0)
    assert second is manager.get_or_build(series, phase_identifier=1)
    assert first is not second
    np.testing.assert_allclose(first.modality_pixels, 10.0)
    np.testing.assert_allclose(second.modality_pixels, 20.0)


def test_render_worker_uses_requested_temporal_phase(tmp_path: Path) -> None:
    series = _cross_series_four_d(tmp_path, phase_count=2)[0]
    catalog = SeriesCatalog()
    catalog._series_by_uid[series.series_instance_uid] = series
    worker = DicomRenderWorker(catalog, VolumeManager())
    results = []
    worker.render_finished.connect(results.append)

    worker.handleRenderRequest(
        MprRenderRequest(
            request_id="phase-1",
            viewport_id="axial",
            series_uid=series.series_instance_uid,
            plane=MprPlane.AXIAL,
            mpr_frame=None,
            phase_identifier=1,
            window=None,
            inverted=False,
        )
    )

    assert len(results) == 1
    assert results[0].phase_identifier == 1
    np.testing.assert_allclose(results[0].modality_pixel, 20.0)


def test_four_d_tab_reuses_mpr_state_when_switching_phase() -> None:
    tab, requests, frame = _ready_four_d_tab()
    viewport_ids = set(tab.viewports_by_id)
    mpr_state = tab._target_mpr_state
    active_viewport = tab.activeViewport
    assert isinstance(active_viewport, MprViewportController)
    active_viewport.apply_pan(13.0, -7.0)
    active_viewport.apply_zoom(1.7)

    tab.setPhaseIndex(1)

    assert len(requests) == 3
    assert {request.phase_identifier for request in requests} == {2}
    assert all(request.mpr_frame == frame for request in requests)
    assert tab.currentPhaseIndex == 0
    _finish_requests(tab, requests, frame)

    assert tab.currentPhaseIndex == 1
    assert tab._target_mpr_state == mpr_state
    assert set(tab.viewports_by_id) == viewport_ids
    assert active_viewport.panX == 13.0
    assert active_viewport.panY == -7.0
    assert active_viewport.zoom == 1.7


def test_four_d_phase_selection_coalesces_and_playback_wraps() -> None:
    tab, requests, frame = _ready_four_d_tab()
    assert tab.fps == 2

    tab.setFps(40)
    assert tab.fps == 15
    tab.setFps(0)
    assert tab.fps == 1
    tab.setFps(15)

    tab.setPhaseIndex(1)
    tab.setPhaseIndex(2)
    assert len(requests) == 3
    _finish_requests(tab, requests, frame)
    assert tab.currentPhaseIndex == 2

    tab.setPlaying(True)
    assert tab.toolController.activeTool == "play"
    assert tab.toolController.activeInteraction == ""
    tab.toolController.activateTool("pan")
    assert tab.toolController.activeTool == "play"
    tab._handle_playback_timeout()
    assert tab.playing
    assert len(requests) == 3
    assert {request.phase_identifier for request in requests} == {1}
    tab._handle_playback_timeout()
    assert len(requests) == 3
    _finish_requests(tab, requests, frame)
    assert tab.currentPhaseIndex == 0

    tab.pausePlayback()
    assert not tab.playing
    tab.toolController.activateTool("pan")
    assert tab.toolController.activeTool == "pan"


def test_four_d_tab_rejects_non_temporal_series() -> None:
    with pytest.raises(ValueError, match="supported temporal series"):
        TabController(
            TabConfig(
                "four-d-tab",
                "4D",
                TabType.FOUR_D,
                (replace(_four_d_meta(), supports_four_d=False),),
            )
        )


def test_four_d_render_failure_pauses_and_restores_previous_phase() -> None:
    tab, requests, frame = _ready_four_d_tab()
    tab.setPhaseIndex(1)
    tab.setPlaying(True)
    failed_request = requests.pop(0)

    tab.handleRenderFailure(
        RenderFailure(
            request_id=failed_request.request_id,
            viewport_id=failed_request.viewport_id,
            error=RuntimeError("phase render failed"),
        )
    )
    _finish_requests(tab, requests, frame)

    assert not tab.playing
    assert tab.currentPhaseIndex == 0
    assert tab._active_mpr_requests == {}


def test_gated_description_links_full_cycle_before_repeated_content_times(tmp_path):
    """Respiratory percentages outrank timestamps shared by several phases."""
    for phase in range(10):
        for slice_index in range(2):
            path = tmp_path / f'phase-{phase}-slice-{slice_index}.dcm'
            _write_phase_slice(path, phase_identifier=phase + 1, phase_count=10,
                               slice_index=slice_index, value=phase * 10)
            ds = pydicom.dcmread(path)
            del ds.TemporalPositionIdentifier
            del ds.NumberOfTemporalPositions
            ds.SeriesInstanceUID = f'1.2.826.0.1.3680043.10.543.30{phase}'
            ds.SeriesDescription = f'P4^P101^S300^I{phase + 3:05d}, Gated, {phase * 10:.1f}%A'
            ds.FrameOfReferenceUID = '1.2.826.0.1.3680043.10.543.999'
            ds.ContentTime = '120000' if phase % 2 else f'1200{phase:02d}'
            ds.save_as(path, enforce_file_format=True)
    records = _scan_series(tmp_path)
    assert len(records) == 10
    assert all(s.supports_four_d and len(s.phases) == 10 for s in records)
    assert all(s.phase_source_keyword == 'SeriesDescriptionPhaseSuffix' for s in records)
    assert [int(pydicom.dcmread(p.instances[0].path).pixel_array[0, 0]) for p in records[0].phases] == list(range(0, 100, 10))


@pytest.mark.parametrize('description', ['Gated 20', 'series 20%A', 'P4, Gated, 120%A', 'P4, Gated, -10%A'])
def test_gated_description_rejects_ambiguous_or_invalid_percentages(description):
    from voxplane.core.dicom_scanner import _series_description_phase_marker
    assert _series_description_phase_marker(description) is None
