from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.model import (
    DicomFolderScanSnapshot,
    DicomInstanceMeta,
    DicomSeriesRecord,
    FrameDisplayMeta,
    ImageGeometryMeta,
    InstanceDisplayMeta,
    MontageRenderResult,
    PixelSpacing,
    RenderFailure,
    SeriesDisplayMeta,
    TabType,
    ToolType,
    TwoDViewType,
    ViewportConfig,
    WindowLevel,
)
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.montage_viewport_controller import (
    MontageViewportController,
)
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider


def _series_meta(slice_count: int = 16) -> SeriesDisplayMeta:
    return SeriesDisplayMeta(
        patient_name="Example Patient",
        patient_id="P001",
        study_description="Study",
        series_description="Axial CT",
        modality="CT",
        series_uid="series-1",
        slice_count=slice_count,
        rows=4,
        columns=6,
        pixel_spacing=PixelSpacing(row=1.0, column=1.0),
    )


def _controller(slice_count: int = 16) -> MontageViewportController:
    meta = _series_meta(slice_count)
    return MontageViewportController(
        ViewportConfig(
            viewport_id="montage-1",
            tab_id="tab-1",
            viewport_type=TwoDViewType.MONTAGE,
            series_uid=meta.series_uid,
            series_meta=meta,
        ),
        ToolController(tab_type=TabType.MONTAGE),
    )


def _result(request, *, window: WindowLevel | None = None) -> MontageRenderResult:
    resolved_window = window or WindowLevel(center=40.0, width=400.0)
    return MontageRenderResult(
        response_id=request.request_id,
        viewport_id=request.viewport_id,
        series_uid=request.series_uid,
        view_type=TwoDViewType.MONTAGE,
        slice_index=request.slice_index,
        image=np.zeros((4, 6), dtype=np.uint8),
        modality_pixel=None,
        frame_meta=FrameDisplayMeta(
            slice_index=request.slice_index,
            slice_count=16,
            window=resolved_window,
            inverted=False,
            instance_meta=InstanceDisplayMeta(
                instance_number=request.slice_index + 1,
                sop_instance_uid=f"sop-{request.slice_index}",
                manufacturer=None,
                kvp=None,
                tube_current_ma=None,
                slice_thickness=None,
                rows=4,
                columns=6,
                pixel_spacing=(1.0, 1.0),
                image_position=None,
                slice_location=None,
            ),
            geometry=ImageGeometryMeta(
                rows=4,
                columns=6,
                pixel_spacing=PixelSpacing(row=1.0, column=1.0),
                image_position_patient=None,
                image_orientation_patient=None,
            ),
        ),
    )


def _accept(controller: MontageViewportController, request) -> None:
    result = _result(request)
    assert controller.accepts_result(result)
    controller.handleRenderResult(result)


def test_montage_defaults_and_column_limits() -> None:
    controller = _controller()

    assert controller.sliceCount == 16
    assert controller.sliceModel.rowCount() == 16
    assert controller.columnCount == 4
    assert controller.imageAspectRatio == 1.5

    controller.setColumnCount(1)
    assert controller.columnCount == 2
    controller.setColumnCount(99)
    assert controller.columnCount == 6


def test_montage_exposes_important_dicom_tag_summaries() -> None:
    meta = replace(
        _series_meta(),
        series_number=2,
        patient_sex="M",
        patient_age="034Y",
        acquisition_datetime="2023.07.24 10:55:38",
        kvp=120.0,
        tube_current_ma=30.0,
        slice_thickness=0.625,
    )
    controller = MontageViewportController(
        ViewportConfig(
            viewport_id="montage-tags",
            tab_id="tab-tags",
            viewport_type=TwoDViewType.MONTAGE,
            series_uid=meta.series_uid,
            series_meta=meta,
        ),
        ToolController(tab_type=TabType.MONTAGE),
    )

    assert controller.patientName == "Example Patient"
    assert controller.patientSummary == "P001 / 男 / 34岁"
    assert controller.descriptionSummary == "Study / Series 2 · Axial CT"
    assert controller.scanParameters == "120 kV / 30 mA"
    assert controller.acquisitionDateTime == "2023.07.24 10:55:38"
    assert controller.sliceThickness == "0.625 mm"


def test_bootstrap_precedes_visible_range_and_then_prioritizes_visible_slices() -> None:
    controller = _controller()
    requests = []
    removals = []
    controller.renderRequested.connect(requests.append)
    controller.imageRemovalRequested.connect(removals.append)

    controller.request_first_loader()
    controller.setVisibleRange(8, 11)

    assert [request.slice_index for request in requests] == [0]
    _accept(controller, requests[0])

    assert controller.windowCenter == 40.0
    assert controller.windowWidth == 400.0
    assert removals == ["montage-1:slice:0"]
    assert requests[1].slice_index == 8


def test_large_series_only_retains_visible_and_adjacent_rows() -> None:
    controller = _controller(320)

    controller.setVisibleRange(120, 131)

    assert controller.sliceModel.rowCount() == 320
    assert controller._visible_indices == set(range(120, 132))
    assert controller._retained_indices == set(range(116, 136))
    assert len(controller._retained_indices) == 20


def test_window_changes_discard_inflight_result_and_coalesce_to_latest_state() -> None:
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.setVisibleRange(0, 3)
    _accept(controller, requests[0])
    stale_request = requests[1]

    controller.applyWindowPreset(80.0, 200.0)
    stale_result = _result(stale_request)

    assert not controller.accepts_result(stale_result)
    assert requests[-1].window == WindowLevel(center=80.0, width=200.0)
    assert len(requests) == 3


def test_global_transform_resets_preserve_column_count() -> None:
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.setVisibleRange(0, 3)
    _accept(controller, requests[0])

    controller.setColumnCount(6)
    controller._interaction_width = 200.0
    controller._interaction_height = 100.0
    controller.apply_pan(40.0, -10.0)
    controller.apply_zoom(2.5)
    controller.applyTransformAction("rotate:cw90")
    controller.applyTransformAction("rotate:mirror-h")

    assert controller.panX == 0.2
    assert controller.panY == -0.1
    assert controller.zoom == 2.5
    assert controller.rotationDegrees == 90.0
    assert controller.horizontalFlip

    controller.reset_tool_state(ToolType.PAN)
    assert (controller.panX, controller.panY) == (0.0, 0.0)
    assert controller.zoom == 2.5

    controller.reset_all_view_state()
    assert controller.zoom == 1.0
    assert controller.rotationDegrees == 0.0
    assert not controller.horizontalFlip
    assert controller.columnCount == 6


def test_open_slice_emits_windowed_2d_navigation() -> None:
    controller = _controller()
    requests = []
    navigation = []
    controller.renderRequested.connect(requests.append)
    controller.sliceOpenRequested.connect(
        lambda *args: navigation.append(args)
    )
    controller.setVisibleRange(0, 3)
    _accept(controller, requests[0])

    controller.applyWindowPreset(70.0, 350.0)
    controller.openSlice(9)

    assert navigation == [("series-1", 9, 70.0, 350.0, False)]


def test_slice_failure_is_local_and_retryable() -> None:
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.setVisibleRange(0, 3)
    _accept(controller, requests[0])
    failed_request = requests[1]

    controller.handleRenderFailure(
        RenderFailure(
            request_id=failed_request.request_id,
            viewport_id=failed_request.viewport_id,
            error=ValueError("broken slice"),
        )
    )

    failed_item = controller._slice_model.item(failed_request.slice_index)
    assert failed_item["loadState"] == "error"
    assert failed_item["errorText"] == "broken slice"
    next_request_count = len(requests)

    controller.retrySlice(failed_request.slice_index)

    assert len(requests) == next_request_count
    # Another visible slice remains in flight; retry is queued without adding
    # a second concurrent request.
    assert failed_request.slice_index in controller._dirty_indices


def test_failed_first_slice_does_not_block_montage_bootstrap() -> None:
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.setVisibleRange(0, 3)
    first_request = requests[0]

    controller.handleRenderFailure(
        RenderFailure(
            request_id=first_request.request_id,
            viewport_id=first_request.viewport_id,
            error=ValueError("broken first slice"),
        )
    )

    assert controller._slice_model.item(0)["loadState"] == "error"
    assert requests[1].slice_index == 1
    _accept(controller, requests[1])
    assert controller.hasWindow
    assert controller._slice_model.item(1)["loadState"] == "ready"


def test_dispose_releases_all_retained_images() -> None:
    controller = _controller()
    requests = []
    removals = []
    controller.renderRequested.connect(requests.append)
    controller.imageRemovalRequested.connect(removals.append)
    controller.setVisibleRange(0, 0)
    _accept(controller, requests[0])

    controller.dispose()

    assert removals == ["montage-1:slice:0"]
    assert controller._active_request is None


def test_montage_tool_whitelist_includes_pseudocolor() -> None:
    tool_controller = ToolController(tab_type=TabType.MONTAGE)
    tools = tool_controller.tools

    assert [item["toolType"] for item in tools] == [
        "window", "pan", "zoom", "rotate", "pseudocolor", "export", "reset",
    ]
    assert next(item for item in tools if item["toolType"] == "pseudocolor")["enabled"]

    tool_controller.activateTool("measure")
    tool_controller.selectInteraction("scroll")
    tool_controller.activateTool("invert")

    assert tool_controller.activeTool == "window"
    assert tool_controller.activeInteraction == "window"


def _catalog(tmp_path: Path) -> SeriesCatalog:
    instance = DicomInstanceMeta(
        path=tmp_path / "slice.dcm",
        patient_name="Example Patient",
        patient_id="P001",
        study_description="Study",
        study_instance_uid="study-1",
        series_description="Axial CT",
        series_instance_uid="series-1",
        series_number=1,
        instance_number=1,
        sop_instance_uid="sop-1",
        pixel_spacing=PixelSpacing(row=1.0, column=1.0),
        modality="CT",
        rows=4,
        columns=6,
        transfer_syntax="Explicit VR Little Endian",
        image_position_patient=None,
        image_orientation_patient=None,
        slice_thickness=None,
        patient_sex="F",
        patient_age="027Y",
        acquisition_datetime="2024.01.02 03:04:05",
        kvp=100.0,
        tube_current_ma=20.0,
    )
    catalog = SeriesCatalog()
    catalog.update(
        DicomFolderScanSnapshot(
            folder=tmp_path,
            total_file_count=1,
            dicom_file_count=1,
            skipped_file_count=0,
            series=[
                DicomSeriesRecord(
                    patient_name=instance.patient_name,
                    patient_id=instance.patient_id,
                    study_description=instance.study_description,
                    study_instance_uid=instance.study_instance_uid,
                    series_description=instance.series_description,
                    series_instance_uid=instance.series_instance_uid,
                    series_number=1,
                    modality="CT",
                    instances=(instance,),
                )
            ],
        )
    )
    return catalog


def test_catalog_carries_montage_tag_metadata(tmp_path) -> None:
    meta = _catalog(tmp_path).get_series_display_meta("series-1")

    assert meta is not None
    assert meta.series_number == 1
    assert meta.patient_sex == "F"
    assert meta.patient_age == "027Y"
    assert meta.acquisition_datetime == "2024.01.02 03:04:05"
    assert meta.kvp == 100.0
    assert meta.tube_current_ma == 20.0


def test_workspace_opens_2d_at_slice_without_initial_slice_request(tmp_path) -> None:
    workspace = WorkspaceController(_catalog(tmp_path), DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)

    workspace.openSeriesSlice("series-1", 7, 75.0, 300.0, False)

    assert workspace.activeTabType == "2d"
    assert len(requests) == 1
    assert requests[0].slice_index == 7
    assert requests[0].window == WindowLevel(center=75.0, width=300.0)
    viewport = workspace.activeViewport
    viewport._state = replace(
        viewport.viewport_state,
        pan_x=0.25,
        zoom=2.0,
        rotation_degrees=90.0,
    )

    workspace.openSeriesSlice("series-1", 3, 60.0, 200.0, False)

    assert requests[-1].slice_index == 3
    assert viewport.panX == 0.25
    assert viewport.zoom == 2.0
    assert viewport.rotationDegrees == 90.0


def test_bootstrap_before_grid_exists_can_reload_first_tile() -> None:
    controller = _controller()
    requests, removals = [], []
    controller.renderRequested.connect(requests.append)
    controller.imageRemovalRequested.connect(removals.append)
    # Workspace first resolves loading before the asynchronous QML grid exists.
    controller.request_first_loader()
    _accept(controller, requests.pop(0))
    assert controller.hasWindow
    assert controller._slice_model.item(0)["loadState"] == "empty"
    assert removals == [controller.image_key(0)]
    controller.setVisibleRange(0, 3)
    assert requests[0].slice_index == 0
    _accept(controller, requests.pop(0))
    assert controller._slice_model.item(0)["loadState"] == "ready"


def test_display_change_during_early_bootstrap_keeps_latest_request() -> None:
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.request_first_loader()
    old = requests.pop(0)
    controller.applyColorMap('blackbody')
    assert not controller.accepts_result(_result(old))
    assert len(requests) == 1 and requests[0].color_map == 'blackbody'
    _accept(controller, requests.pop(0))
    controller.setVisibleRange(0, 3)
    assert requests[0].slice_index == 0
    _accept(controller, requests.pop(0))
    assert controller._slice_model.item(0)["loadState"] == "ready"
