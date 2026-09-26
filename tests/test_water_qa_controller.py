from dataclasses import replace
from threading import Event
import time

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QThread

from qt_dicom_viewer.core.water_qa import analyze_water_phantom
from qt_dicom_viewer.model import PixelSpacing, ToolType, WindowLevel
from qt_dicom_viewer.ui.controller.viewport.controller.water_qa_controller import WaterQaController
from test_measurement_qml import qt_app
from test_viewport_transform import _controller, _render_result
from test_water_qa import water_image


def deliver_frame(view, frame):
    # These fixtures emulate a newly completed render of the requested slice.
    # QA/MTF task staleness is tested independently of renderer request IDs.
    view.handleRenderResult(replace(frame, response_id=view._latest_request_id or frame.response_id))


def water_render(view, index=0, spacing=(1, 1), pixels=None):
    base = _render_result(view)
    pixels = water_image(mean=2+index*3) if pixels is None else pixels
    rows, columns = pixels.shape
    meta = replace(base.frame_meta, slice_index=index, slice_count=4,
                   geometry=replace(base.frame_meta.geometry, rows=rows, columns=columns,
                                    pixel_spacing=PixelSpacing(*spacing)),
                   instance_meta=replace(base.frame_meta.instance_meta, rows=rows, columns=columns,
                                         pixel_spacing=spacing, sop_instance_uid=f"water-{index}"))
    return replace(base, series_uid=view.viewport_config.series_uid, frame_meta=meta,
                   modality_pixel=pixels, image=np.clip((pixels+150)*255/300, 0, 255).astype(np.uint8))


@pytest.fixture
def qa_view(qt_app):
    view = _controller()
    frame = water_render(view)
    deliver_frame(view, frame)
    try:
        yield view, frame
    finally:
        view.shutdown()


def pump_until(app, condition):
    deadline = time.monotonic()+5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    app.processEvents()
    assert condition(), "后台 QA 未及时完成"


def wait_qa(app, controller):
    pump_until(app, lambda: controller.status != "calculating")
    assert controller.status == "ready", controller.error


def finish(qa, job):
    token, key, pixels, spacing, settings = job
    result = analyze_water_phantom(pixels, spacing, settings)
    qa._receive_result(token, key, result, "")
    return result


def test_service_activation_runs_worker_and_returns_five_rois_on_gui_thread(qa_view, qt_app):
    view, _ = qa_view
    qa, tools = view.qaController, view._tool_controller
    threads = []
    qa.stateChanged.connect(lambda: threads.append(QThread.currentThread()))
    assert qa.status == "empty" and not qa.enabled
    tools.selectService("service:qa")
    wait_qa(qt_app, qa)
    assert qa.enabled and len(qa.roiItems) == 5
    assert qa.currentResult["noise_hu"] == pytest.approx(5, abs=1)
    assert tools.activeInteraction == "service:qa"
    assert tools.resetLabel == "重置水模 QA"
    assert view.measurementController.measurementItems == []
    assert view.mtfController.roiController.measurementItems == []
    assert all(thread == view.thread() for thread in threads)
    assert not {"passed", "failed", "grade", "tolerance"} & qa.currentResult.keys()


def test_display_changes_reuse_result_and_resets_are_scoped(qa_view, qt_app):
    view, frame = qa_view
    tools, qa = view._tool_controller, view.qaController
    tools.resetRequested.connect(lambda tool: view.reset_tool_state(ToolType(tool)))
    tools.selectService("service:qa")
    wait_qa(qt_app, qa)
    original = qa.currentResult
    token = qa._token
    tools.activateTool("pan")
    view.apply_pan(20, -30)
    view.apply_zoom(1.4)
    view.applyTransformAction("rotate:cw90")
    view.applyTransformAction("rotate:mirror-h")
    deliver_frame(view, replace(frame, image=255-frame.image,
        frame_meta=replace(frame.frame_meta, window=WindowLevel(100, 500), inverted=True)))
    assert qa.currentResult == original and qa._token == token
    view.reset_tool_state(ToolType.MEASURE)
    assert qa.currentResult == original
    tools.activateTool("service")
    tools.resetActiveTool()
    assert not qa.enabled and qa.currentResult == {} and not qa.roiItems
    assert qa.roiDiameterMm == qa.edgeClearanceMm == 20
    tools.selectService("service:qa")  # Reselecting the same service restarts after reset.
    wait_qa(qt_app, qa)
    view.reset_all_view_state()
    assert not qa.enabled and qa.currentResult == {}


def test_auto_activation_before_load_and_missing_pixel_spacing(qt_app):
    view = _controller()
    try:
        tools, qa = view._tool_controller, view.qaController
        tools.selectService("service:qa")
        assert qa.status == "waiting"
        frame = water_render(view)
        deliver_frame(view, frame)
        wait_qa(qt_app, qa)
        missing = replace(frame, frame_meta=replace(frame.frame_meta,
            instance_meta=replace(frame.frame_meta.instance_meta, pixel_spacing=None)))
        deliver_frame(view, missing)
        pump_until(qt_app, lambda: qa.status != "calculating")
        assert qa.status == "error" and "PixelSpacing" in qa.error
        assert qa.currentResult == {} and not qa.roiItems
    finally:
        view.shutdown()


def test_parameter_edits_discard_old_results_and_update_geometry(qa_view, qt_app):
    view, _ = qa_view
    qa = view.qaController
    qa.activate()
    wait_qa(qt_app, qa)
    previous = qa.currentResult
    qa.setRoiDiameterMm(30)
    assert qa.currentResult == {} and not qa.roiItems
    wait_qa(qt_app, qa)
    assert qa.currentResult["rois"][0]["area_mm2"] > previous["rois"][0]["area_mm2"]
    qa.setEdgeClearanceMm(10)
    wait_qa(qt_app, qa)
    assert qa.currentResult["settings"]["edge_clearance_mm"] == 10
    qa.setRoiDiameterMm(100)
    pump_until(qt_app, lambda: qa.status != "calculating")
    assert qa.status == "error" and qa.roiItems == []
    assert "互不重叠" in qa.error
    qa.setRoiDiameterMm(20)
    wait_qa(qt_app, qa)


def test_slice_cache_stale_callbacks_reset_and_changed_raw_pixels(qa_view, monkeypatch):
    view, first = qa_view
    qa = view.qaController
    jobs = []
    monkeypatch.setattr(qa, "_submit", lambda *args: jobs.append(args))
    qa.activate()
    old = jobs[-1]
    view.apply_slice_index(1)
    assert not qa.roiItems and qa.currentResult == {} and qa.status == "waiting"
    second = water_render(view, 1)
    deliver_frame(view, second)
    latest = jobs[-1]
    finish(qa, old)
    assert qa.status == "calculating" and not qa.currentResult
    finish(qa, latest)
    result_second = qa.currentResult
    view.apply_slice_index(0)
    deliver_frame(view, first)
    finish(qa, jobs[-1])
    count = len(jobs)
    view.apply_slice_index(1)
    deliver_frame(view, second)
    assert len(jobs) == count and qa.currentResult == result_second
    modified = replace(second, modality_pixel=second.modality_pixel+1)
    deliver_frame(view, modified)
    assert len(jobs) == count+1
    latest = jobs[-1]
    qa.reset()
    finish(qa, latest)
    assert not qa.enabled and not qa.currentResult


def test_fast_slice_changes_coalesce_to_latest_snapshot(qa_view, qt_app, monkeypatch):
    view, _ = qa_view
    qa = view.qaController
    entered, release = Event(), Event()
    calls = []
    def delayed(pixels, spacing, settings):
        calls.append(float(np.median(pixels[100:180, 180:230])))
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return analyze_water_phantom(pixels, spacing, settings)
    monkeypatch.setattr("qt_dicom_viewer.ui.controller.viewport.controller.water_qa_controller.analyze_water_phantom", delayed)
    qa.activate()
    pump_until(qt_app, entered.is_set)
    try:
        for index in (1, 2, 3):
            view.apply_slice_index(index)
            deliver_frame(view, water_render(view, index))
            assert len(qa._tasks) == 1 and qa._pending is not None
    finally:
        release.set()
    wait_qa(qt_app, qa)
    assert len(calls) == 2
    assert qa.currentResult["water_ct_hu"] == pytest.approx(11, abs=1)


def test_snapshots_independent_viewports_and_shutdown_ignore_callbacks(qa_view, monkeypatch):
    view, frame = qa_view
    qa = view.qaController
    jobs = []
    monkeypatch.setattr(qa, "_submit", lambda *args: jobs.append(args))
    qa.activate()
    job = jobs[-1]
    frame.modality_pixel[:] = -1000
    result = finish(qa, job)
    assert result.water_ct_hu == pytest.approx(2, abs=1)
    other = _controller()
    try:
        assert not other.qaController.enabled and not other.qaController.currentResult
        qa.shutdown()
        qa._receive_result(job[0], job[1], result, "")
        qa.activate()
        assert not qa.enabled and not qa.currentResult
    finally:
        other.shutdown()
    mr = WaterQaController("MR")
    mr.activate()
    assert not mr.available and not mr.enabled
    mr.shutdown()


def drag_qa(view, index=0, dx=8, dy=6, commit=True):
    roi = view.qaController.currentResult["rois"][index]
    column, row = roi["column"], roi["row"]
    view.beginInteraction(100, 100, 1, True, column, row, 3, 2)
    view.updateInteraction(QPointF(100, 100), QPointF(108, 106), QPointF(8, 6),
                           QPointF(8, 6), True, column+dx, row+dy)
    if commit:
        view.endInteraction(108, 106, True, column+dx, row+dy)


def test_manual_drag_remeasures_and_caches_each_slice_without_detection(qa_view, qt_app, monkeypatch):
    view, frame = qa_view
    qa, tools = view.qaController, view._tool_controller
    tools.selectService("service:qa")
    wait_qa(qt_app, qa)
    original = qa.currentResult
    def unexpected_detection(*args):
        pytest.fail("Dragging must not redetect or replace other ROI positions")
    monkeypatch.setattr(qa, "_submit", unexpected_detection)
    for index in range(5):
        before = qa.currentResult["rois"]
        drag_qa(view, index)
        after = qa.currentResult["rois"]
        assert not qa.dragging and qa.status == "ready" and not qa.error
        for j in range(5):
            assert after[j]["column"] == pytest.approx(before[j]["column"]+(8 if index == j else 0))
            assert after[j]["row"] == pytest.approx(before[j]["row"]+(6 if index == j else 0))
    saved = qa.currentResult
    assert saved["water_ct_hu"] != original["water_ct_hu"]
    tools.activateTool("pan")
    drag_qa(view)
    assert qa.currentResult == saved
    tools.activateTool("service")
    assert tools.activeInteraction == "service:qa"
    view.apply_slice_index(1)
    assert qa.currentResult == {}
    view.apply_slice_index(0)
    deliver_frame(view, frame)
    assert qa.currentResult == saved
    view.applyTransformAction("rotate:mirror-h")
    deliver_frame(view, replace(frame, image=255-frame.image))
    assert qa.currentResult == saved


def test_drag_preview_cancel_overlap_and_bounds_keep_complete_results(qa_view, qt_app):
    view, frame = qa_view
    qa, tools = view.qaController, view._tool_controller
    tools.selectService("service:qa")
    wait_qa(qt_app, qa)
    saved = qa.currentResult
    for cancel in (view.cancelMeasurement, lambda: tools.activateTool("pan")):
        drag_qa(view, commit=False)
        assert qa.dragging and qa.roiItems[0]["editing"]
        assert qa.roiItems[0]["column"] == pytest.approx(saved["rois"][0]["column"]+8)
        assert qa.currentResult == saved
        cancel()
        assert not qa.dragging and qa.currentResult == saved
        tools.activateTool("service")
    center, left = saved["rois"][:2]
    drag_qa(view, dx=left["column"]-center["column"], dy=0)
    assert "重叠" in qa.error and qa.currentResult == saved
    drag_qa(view, index=2, dx=10000, dy=4000)
    assert not qa.error
    roi, phantom = qa.currentResult["rois"][2], saved["phantom"]
    distance = np.hypot(roi["column"]-phantom["column"], roi["row"]-phantom["row"])
    assert distance+roi["radius_mm"] == pytest.approx(phantom["radius_mm"])
    drag_qa(view, commit=False)
    view.apply_slice_index(1)
    assert not qa.dragging and qa.roiItems == []
    view.endInteraction(0, 0, True, 0, 0)
    view.apply_slice_index(0)
    deliver_frame(view, frame)
    assert qa.currentResult["rois"][0] == saved["rois"][0]
    moved = qa.currentResult
    qa.analyze()
    wait_qa(qt_app, qa)
    assert qa.currentResult == moved


def test_copies_are_independent_protected_baselines_and_slice_cached(qa_view, qt_app):
    view, frame = qa_view
    qa = view.qaController
    view._tool_controller.selectService('service:qa')
    wait_qa(qt_app, qa)
    baseline = qa.currentResult
    summary = {k: v for k, v in baseline.items() if k != 'rois'}
    for roi in baseline['rois']:
        assert not roi['removable']
        assert not qa.deleteRoi(roi['key'])
    assert qa.copyRoi('center')
    assert qa.copyRoi('extra-1')
    assert len(qa.roiItems) == 7
    assert all(r['removable'] for r in qa.currentResult['rois'][5:])
    assert qa.currentResult['rois'][:5] == baseline['rois']
    assert {k:v for k,v in qa.currentResult.items() if k != 'rois'} == summary
    before = qa.currentResult['rois'][5]
    drag_qa(view, index=5, dx=3, dy=-2)
    moved = qa.currentResult['rois'][5]
    assert moved['column'] == pytest.approx(before['column']+3)
    assert moved['row'] == pytest.approx(before['row']-2)
    assert qa.currentResult['rois'][:5] == baseline['rois']
    assert {k:v for k,v in qa.currentResult.items() if k != 'rois'} == summary
    saved = qa.currentResult
    view.setSliceIndex(1)
    deliver_frame(view, water_render(view, 1))
    wait_qa(qt_app, qa)
    assert len(qa.roiItems) == 5
    view.setSliceIndex(0)
    deliver_frame(view, frame)
    assert qa.currentResult == saved
    # Controller and keyboard paths both enforce protection.
    qa._selected_key = 'center'
    view.deleteSelectedMeasurement()
    assert len(qa.roiItems) == 7
    qa._selected_key = 'extra-1'
    view.deleteSelectedMeasurement()
    assert len(qa.roiItems) == 6
    assert qa.deleteRoi('extra-2')
    assert qa.currentResult == baseline
    assert not qa.deleteRoi('extra-2')
    assert not qa.copyRoi('missing')
