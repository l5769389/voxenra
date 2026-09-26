"""验证提交边界、切片缓存及乱序任务，显示变换不属于重算条件。"""

from dataclasses import replace
from threading import Event
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QPointF, QThread
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.bead_mtf import compute_point_source_mtf, compute_mtf_with_context
from qt_dicom_viewer.core.ramp_fwhm import compute_ramp_fwhm
from qt_dicom_viewer.model import PixelSpacing, TabType, ToolType, WindowLevel
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from test_bead_mtf import gaussian
from test_measurement_qml import qt_app
from test_viewport_transform import _controller, _render_result


def deliver_frame(view, frame):
    # These fixtures emulate a newly completed render of the requested slice.
    # QA/MTF task staleness is tested independently of renderer request IDs.
    view.handleRenderResult(replace(frame, response_id=view._latest_request_id or frame.response_id))


def bead_render(viewport):
    base = _render_result(viewport)
    # Compact point response leaves the full source-scaled background annulus
    # inside the drawn ROI. Wider synthetic PSFs are tested by the core suite.
    pixels = gaussian(sigma_x=.2, sigma_y=.15)
    return replace(base, modality_pixel=pixels, image=np.clip(pixels / 5, 0, 255).astype(np.uint8),
                   frame_meta=replace(base.frame_meta, slice_count=3,
                       geometry=replace(base.frame_meta.geometry, rows=128, columns=128,
                                        pixel_spacing=PixelSpacing(.15, .1)),
                       instance_meta=replace(base.frame_meta.instance_meta, rows=128, columns=128,
                                             pixel_spacing=(.15, .1))))


@pytest.fixture
def mtf_viewport(qt_app):
    view = _controller()
    # These tests cover the measured-spectrum mode; equivalent mode is tested
    # separately, including the enabled-by-default application preference.
    view.settingsController.setValue('services', 'mtfGaussianEquivalent', False)
    frame = bead_render(view)
    deliver_frame(view, frame)
    view._tool_controller.selectService("service:mtf")
    try:
        yield view, frame
    finally:
        view.shutdown()


def draw(view, start=(8, 8), end=(118, 118)):
    view.beginInteraction(0, 0, 1, True, *start, .1, .1)
    view.endInteraction(50, 50, True, *end)


def wait_result(controller):
    # Qt's qWait loop can starve NumPy workers when they reacquire the GIL.
    # Process UI events and explicitly yield, as the other worker tests do.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if controller.status != "calculating":
            return
        time.sleep(.005)
    pytest.fail("后台 MTF 未在超时内完成")


def capture_tasks(view, monkeypatch, controller=None):
    jobs = []
    monkeypatch.setattr(controller or view.mtfController, "_submit", lambda *args: jobs.append(args))
    return jobs


def finish(view, job):
    token, pixels, spacing, context = job
    result = compute_ramp_fwhm(pixels, *spacing, direction=token.ramp_direction,
                              analysis_method=token.analysis_method) if token.measurement_method == "ramp" else compute_mtf_with_context(
        pixels,
        *spacing,
        context=context,
        measurement_method=token.measurement_method,
        analysis_method=token.analysis_method,
    )
    target = view.fwhmController if token.measurement_method == "ramp" else view.mtfController
    target._receive_result(token, result, "")
    return result


def test_numeric_roi_commit_is_atomic_square_and_rejects_stale_results(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    controller = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    assert controller.applyRoi(63, 63, 8, 3)
    assert len(jobs) == 1
    geometry = controller.roiGeometry
    assert geometry['width'] == pytest.approx(8)
    assert geometry['height'] == pytest.approx(8)  # Anisotropic pixels, physical square.
    assert controller.stateSnapshot['status'] == 'calculating'
    assert controller.stateSnapshot['result'] == {}
    first = jobs[0]
    assert controller.applyRoi(64, 64, 9, 9)
    assert len(controller.roiController.visible_measurements) == 1
    finish(view, first)
    assert controller.status == 'calculating'
    finish(view, jobs[1])
    assert controller.stateSnapshot['status'] == 'ready'
    assert controller.stateSnapshot['sliceNumber'] == frame.frame_meta.slice_index + 1
    saved = controller.stateSnapshot
    for values in [(0, 0, 9, 9), (63, 63, 0, 1), (63, 63, .01, .01),
                   (float('nan'), 63, 9, 9), (63, 63, float('inf'), 9)]:
        assert not controller.applyRoi(*values)
        assert controller.stateSnapshot == saved
    assert len(jobs) == 2
    controller.set_current_slice(1)
    assert controller.stateSnapshot['result'] == {}
    assert controller.frameToken == ''
    assert not controller.applyRoi(63, 63, 8, 8)


def test_numeric_fwhm_roi_keeps_rectangle_and_separate_cache(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    mtf, fwhm = view.mtfController, view.fwhmController
    jobs = capture_tasks(view, monkeypatch, fwhm)
    assert fwhm.applyRoi(60, 60, 5, 2)
    assert fwhm.roiGeometry['width'] == pytest.approx(5)
    assert fwhm.roiGeometry['height'] == pytest.approx(2)
    assert len(jobs) == 1
    assert not mtf.roiController.visible_measurements


def test_numeric_roi_requires_real_spacing_and_no_pointer_transaction(mtf_viewport):
    view, frame = mtf_viewport
    controller = view.mtfController
    view.beginInteraction(0, 0, 1, True, 8, 8, .1, .1)
    assert not controller.applyRoi(63, 63, 8, 8)
    view.cancelMeasurement()
    controller.set_frame('series', replace(frame.frame_meta,
        instance_meta=replace(frame.frame_meta.instance_meta, pixel_spacing=None)), frame.modality_pixel)
    assert controller.roiGeometry == {}
    assert not controller.applyRoi(63, 63, 8, 8)


def test_real_thread_result_and_independent_measurements(mtf_viewport):
    view, _ = mtf_viewport
    callback_threads = []
    view.mtfController.stateChanged.connect(lambda: callback_threads.append(QThread.currentThread()))
    draw(view, (118, 118), (8, 8))
    wait_result(view.mtfController)
    assert view.mtfController.status == "ready"
    assert view.mtfController.currentResult["x"]["mtf50"] > 0
    assert view.measurementController.measurementItems == []
    roi = view.mtfController.roiController.measurementItems
    assert len(roi) == 1 and roi[0]["metrics"]["pixel_count"] == 0
    view._tool_controller.selectInteraction("measure:rect")
    draw(view)
    assert len(view.measurementController.measurementItems) == 1
    view.reset_tool_state(ToolType.MEASURE)
    assert view.measurementController.measurementItems == []
    assert view.mtfController.roiController.measurementItems == roi
    assert all(thread == view.thread() for thread in callback_threads)


def test_method_defaults_switching_and_analysis_recalculation(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    controller = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    assert controller.measurementMethod == "bead"
    assert controller.analysisMethod == "tukey_fft"
    controller.setShowY(True)

    draw(view)
    finish(view, jobs[-1])
    roi = controller.roiController.measurementItems
    direct_value = controller.currentResult["x"]["mtf50"]

    controller.setAnalysisMethod("gaussian")
    assert controller.analysisMethod == "gaussian"
    assert controller.roiController.measurementItems == roi
    assert controller.status == "calculating"
    assert jobs[-1][0].analysis_method == "gaussian"
    finish(view, jobs[-1])
    assert controller.analysisMethod == "gaussian"
    assert controller.currentResult["x"]["mtf50"] != direct_value
    assert controller.statusText == ""
    assert controller.roiMetricLabel == (
        "ROI  11.00 × 11.00 mm · 121.00 mm²\n"
        f"MTF50  X {controller.currentResult['x']['mtf50']:.2f} · "
        f"Y {controller.currentResult['y']['mtf50']:.2f} lp/mm\n"
        f"MTF10  X {controller.currentResult['x']['mtf10']:.2f} · "
        f"Y {controller.currentResult['y']['mtf10']:.2f} lp/mm"
    )

    controller.setMeasurementMethod("wire")
    assert controller.measurementMethod == "wire"

    assert controller.status == "empty"
    assert not controller.roiController.measurementItems
    assert controller.currentResult == {}
    assert controller.roiMetricLabel == ""
    assert "细丝截面" in controller.statusText

    draw(view)
    assert jobs[-1][0].measurement_method == "wire"
    assert jobs[-1][0].analysis_method == "gaussian"
    finish(view, jobs[-1])
    assert controller.measurementMethod == "wire"


def test_automatic_weighting_reports_actual_method_without_an_extra_selector(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    c = view.mtfController
    t = np.arange(128) - 63.5
    positive = np.exp(-.5 * (t / 2)**2)
    negative = positive - .18 * np.exp(-.5 * ((t - 7) / 2)**2)
    deliver_frame(view, replace(frame, modality_pixel=80 + 1000 * np.outer(positive, negative)))
    jobs = capture_tasks(view, monkeypatch)
    draw(view, (20, 34), (108, 93))
    first = jobs[-1]
    finish(view, first)
    assert c.status == "ready"
    assert c.analysisMethod == 'tukey_fft' and c.actualAnalysisMethod == 'tukey_fft'
    assert {m['value'] for m in c.analysisMethods} == {'direct_fft', 'gaussian', 'tukey_fft'}
    weighted = c.currentResult
    roi = c.roiController.measurementItems
    c.setAnalysisMethod('gaussian')
    assert c.actualAnalysisMethod == '' and c.currentResult == {}
    finish(view, first)
    assert c.status == 'calculating'
    finish(view, jobs[-1])
    # 负旁瓣下高斯拟合自动切换到实测加权频谱。
    assert c.analysisMethod == 'gaussian' and c.actualAnalysisMethod == 'tukey_fft'
    assert c.roiController.measurementItems == roi
    for axis in ('x', 'y'):
        assert c.currentResult[axis]['fwhm'] == weighted[axis]['fwhm']


def test_only_commit_submits_and_display_operations_do_not_recompute(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    view.beginInteraction(0, 0, 1, True, 8, 8, .1, .1)
    view.updateInteraction(QPointF(), QPointF(50, 50), QPointF(50, 50), QPointF(50, 50), True, 118, 118)
    assert view.mtfController.status == "editing"
    assert view.mtfController.currentResult == {}
    assert not jobs
    view.endInteraction(50, 50, True, 118, 118)
    assert len(jobs) == 1
    finish(view, jobs[0])
    saved = view.mtfController.currentResult
    view.applyTransformAction("rotate:cw90")
    view.applyTransformAction("rotate:mirror-h")
    view.apply_zoom(2)
    view._tool_controller.activateTool("pan")
    view.beginInteraction(0, 0, 1, True, 30, 30, .1, .1)
    view.updateInteraction(QPointF(), QPointF(10, 10), QPointF(10, 10), QPointF(10, 10), True, 40, 40)
    view.endInteraction(10, 10, True, 40, 40)
    deliver_frame(view, replace(frame, frame_meta=replace(frame.frame_meta, window=WindowLevel(100, 1000))))
    view.updateCursorPosition(10, 10, 20, 20, 20, 20, True, .1, .1)
    assert len(jobs) == 1
    assert view.mtfController.currentResult == saved
    view.deleteSelectedMeasurement()  # 非 MTF 模式不能删除 MTF ROI。
    assert len(view.mtfController.roiController.measurementItems) == 1


def test_mtf_roi_draw_and_corner_resize_stay_physically_square(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    capture_tasks(view, monkeypatch)

    draw(view, (20, 30), (70, 50))
    roi = view.mtfController.roiController.measurementItems[0]
    assert roi["metrics"]["width_mm"] == pytest.approx(3)
    assert roi["metrics"]["height_mm"] == pytest.approx(3)
    assert roi["points"][1]["column"] == pytest.approx(20 + 3 / .1)

    # 右下角向非正方形方向拖动，编辑后仍保持物理宽高相等。
    corner = roi["points"][1]
    draw(view, (corner["column"], corner["row"]), (90, 55))
    resized = view.mtfController.roiController.measurementItems[0]
    assert resized["metrics"]["width_mm"] == pytest.approx(
        resized["metrics"]["height_mm"]
    )

    # 普通矩形仍按自由宽高绘制。
    view._tool_controller.selectInteraction("measure:rect")
    draw(view, (20, 30), (70, 50))
    ordinary = view.measurementController.measurementItems[0]
    assert ordinary["metrics"]["width_mm"] == pytest.approx(5)
    assert ordinary["metrics"]["height_mm"] == pytest.approx(3)


def test_move_resize_cancel_replace_and_stale_versions(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    draw(view, (10, 20), (110, 110))
    finish(view, jobs[0])
    initial = view.mtfController.currentResult
    roi = view.mtfController.roiController
    first_id = roi.measurementItems[0]["measurementId"]
    view.beginInteraction(0, 0, 1, True, 50, 50, .1, .1)
    assert view.mtfController.status == "editing" and view.mtfController.currentResult == {}
    view.cancelMeasurement()
    assert view.mtfController.currentResult == initial
    draw(view, (50, 50), (55, 56))  # 内部整体移动。
    moved = roi.measurementItems[0]
    assert moved["points"] == [
        {"column": 15, "row": 26},
        {"column": 115, "row": pytest.approx(92.6666667)},
    ]
    corner = moved["points"][1]
    draw(view, (corner["column"], corner["row"]), (116, 118))  # 调整角点。
    assert roi.measurementItems[0]["measurementId"] == first_id
    newest = finish(view, jobs[2])
    finish(view, jobs[1])  # 旧移动请求不得覆盖新的缩放结果。
    assert view.mtfController.currentResult["x"]["mtf50"] == newest.x.mtf50
    view.beginInteraction(0, 0, 1, True, 2, 2, .1, .1)
    view.cancelMeasurement()
    assert roi.measurementItems[0]["measurementId"] == first_id
    draw(view, (2, 2), (124, 124))
    assert len(roi.measurementItems) == 1
    assert roi.measurementItems[0]["measurementId"] != first_id
    finish(view, jobs[0])
    assert view.mtfController.status == "calculating"


def test_slice_geometry_and_instance_isolation_and_restore(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    first_roi = view.mtfController.roiController.measurementItems
    view.apply_slice_index(1)
    assert view.mtfController.status == "empty"
    assert not view.mtfController.roiController.measurementItems
    finish(view, jobs[0])
    assert view.mtfController.currentResult == {}
    other = replace(frame, frame_meta=replace(frame.frame_meta, slice_index=1))
    deliver_frame(view, other)
    draw(view)
    finish(view, jobs[1])
    assert len(view.mtfController.roiController.committed_measurements) == 2
    deliver_frame(view, frame)
    assert view.mtfController.roiController.measurementItems == first_roi
    assert view.mtfController.status == "ready"
    for changed in [replace(frame.frame_meta, instance_meta=replace(frame.frame_meta.instance_meta, sop_instance_uid="other")),
                    replace(frame.frame_meta, geometry=replace(frame.frame_meta.geometry, image_position_patient=(1, 2, 3)))]:
        deliver_frame(view, replace(frame, frame_meta=changed))
        assert view.mtfController.status == "empty"
        assert not view.mtfController.roiController.measurementItems
    deliver_frame(view, frame)
    assert view.mtfController.status == "ready"
    assert len(jobs) == 2


@pytest.mark.parametrize("action", ["delete", "reset", "global", "close"])
def test_late_result_after_removal_is_ignored(mtf_viewport, monkeypatch, action):
    view, _ = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    if action == "delete":
        view.deleteSelectedMeasurement()
    elif action == "reset":
        view.reset_tool_state(ToolType.SERVICE)
    elif action == "global":
        view.reset_all_view_state()
    else:
        view.shutdown()
    finish(view, jobs[0])
    assert view.mtfController.currentResult == {}
    assert not view.mtfController.roiController.committed_measurements


def test_failed_current_roi_hides_previous_result_and_no_spacing_fallback(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    finish(view, jobs[0])
    draw(view, (8, 8), (-10, -10))
    assert view.mtfController.status == "error" and "超出" in view.mtfController.error
    assert view.mtfController.currentResult == {}
    assert len(jobs) == 1
    assert 'mm²' in view.mtfController.roiMetricLabel
    assert 'MTF50' not in view.mtfController.roiMetricLabel
    no_spacing = replace(frame, frame_meta=replace(frame.frame_meta,
                         instance_meta=replace(frame.frame_meta.instance_meta, pixel_spacing=None)))
    deliver_frame(view, no_spacing)
    draw(view, (20, 20), (110, 110))
    assert "PixelSpacing" in view.mtfController.error
    assert len(jobs) == 1
    assert 'px²' in view.mtfController.roiMetricLabel
    assert 'mm' not in view.mtfController.roiMetricLabel


def test_reset_mtf_clears_all_slices_but_not_normal_measurements(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    capture_tasks(view, monkeypatch)
    draw(view)
    deliver_frame(view, replace(frame, frame_meta=replace(frame.frame_meta, slice_index=1)))
    draw(view)
    view._tool_controller.selectInteraction("measure:rect")
    draw(view)
    saved = view.measurementController.measurementItems
    view._tool_controller.selectService("service:mtf")
    view.reset_tool_state(ToolType.SERVICE)
    assert not view.mtfController.roiController.committed_measurements
    assert view.measurementController.measurementItems == saved
    view.reset_all_view_state()
    assert not view.measurementController.committed_measurements


@pytest.mark.parametrize("tab_type", [TabType.MPR, TabType.THREE_D, TabType.FOUR_D, TabType.TAG])
def test_direct_mtf_interaction_cannot_bypass_tab_gate(tab_type):
    tools = ToolController(tab_type=tab_type)
    initial_interaction = tools.activeInteraction
    tools.selectInteraction("service:mtf")
    assert tools.activeInteraction == initial_interaction


def test_snapshot_is_independent_of_subsequent_source_mutation(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    snapshot = jobs[0][1].copy()
    background = jobs[0][3][0].copy()
    frame.modality_pixel[:] = 0
    np.testing.assert_array_equal(jobs[0][1], snapshot)
    np.testing.assert_array_equal(jobs[0][3][0], background)
    assert not jobs[0][3][0].flags.writeable


@pytest.mark.parametrize("action", ["delete", "page", "close"])
def test_real_inflight_worker_does_not_access_removed_or_other_slice(mtf_viewport, monkeypatch, action):
    view, frame = mtf_viewport
    started, release, finished = Event(), Event(), Event()

    def slow_compute(*args, **kwargs):
        started.set()
        assert release.wait(3)
        try:
            return compute_mtf_with_context(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(
        "qt_dicom_viewer.ui.controller.viewport.controller.mtf_controller.compute_mtf_with_context",
        slow_compute,
    )
    try:
        draw(view)
        assert started.wait(2)
        assert view.mtfController.status == "calculating"
        if action == "delete":
            view.deleteSelectedMeasurement()
        elif action == "page":
            view.apply_slice_index(1)
            deliver_frame(view, replace(frame, frame_meta=replace(frame.frame_meta, slice_index=1)))
        release.set()
        if action == "close":
            view.shutdown()
        assert finished.wait(2)
        QTest.qWait(30)
        assert view.mtfController.currentResult == {}
        assert view.mtfController.status == "empty"
    finally:
        release.set()


def test_two_viewports_with_same_slice_have_independent_rois(mtf_viewport, monkeypatch):
    first, frame = mtf_viewport
    capture_tasks(first, monkeypatch)
    second = _controller()
    try:
        second.handleRenderResult(frame)
        second._tool_controller.selectService("service:mtf")
        capture_tasks(second, monkeypatch)
        draw(first)
        assert not second.mtfController.roiController.measurementItems
        draw(second)
        first.mtfController.reset()
        assert len(second.mtfController.roiController.measurementItems) == 1
    finally:
        second.shutdown()


def test_mtf_precision_refreshes_labels_without_new_analysis(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    controller = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    finish(view, jobs[-1])
    raw = controller.currentResult
    job_count = len(jobs)
    view.settingsController.setValue("measurement", "decimalPlaces", 0)
    assert controller.roiMetricLabel.startswith("ROI  11 × 11 mm")
    view.settingsController.setValue("measurement", "decimalPlaces", 3)
    assert controller.roiMetricLabel.startswith("ROI  11.000 × 11.000 mm")
    assert controller.currentResult == raw and len(jobs) == job_count


def test_mtf_unit_change_rescales_every_frequency_without_recomputing_or_mutating_cache(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    c = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    result = finish(view, jobs[-1])
    original = c.currentResult
    label = c.roiMetricLabel
    for _ in range(2):
        assert view.settingsController.setValue("services", "mtfFrequencyUnit", "lp/cm")
        assert c.frequencyUnit == "lp/cm"
        assert 'lp/mm' not in c.roiMetricLabel and c.roiMetricLabel.count('lp/cm') == 2
        assert c.roiMetricLabel.splitlines()[0] == label.splitlines()[0]
        for axis in ('x', 'y'):
            display = c.currentResult[axis]
            np.testing.assert_allclose(display['frequency'], np.array(original[axis]['frequency']) * 10)
            for field in ('mtf50', 'mtf10'):
                assert display[field] == pytest.approx(original[axis][field] * 10)
            assert display['fwhm'] == original[axis]['fwhm']
            assert display['mtf'] == original[axis]['mtf'] and display['lsf'] == original[axis]['lsf']
        assert len(jobs) == 1 and c._current_analysis().result is result
        view.settingsController.setValue("services", "mtfFrequencyUnit", "lp/mm")
        assert c.currentResult == original and c.roiMetricLabel == label


def test_mtf_units_preserve_missing_crossings(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    pixels = np.zeros((128, 128)); pixels[64, 64] = 100
    deliver_frame(view, replace(frame, modality_pixel=pixels))
    view.mtfController.setAnalysisMethod('direct_fft')
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    finish(view, jobs[-1])
    view.settingsController.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
    for axis in ('x', 'y'):
        assert view.mtfController.currentResult[axis]['mtf10'] is None
    assert '未达到' in view.mtfController.roiMetricLabel


def test_ramp_roi_is_rectangular_and_angle_changes_do_not_recompute(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    c = view.fwhmController
    view._tool_controller.selectService('service:fwhm')
    assert '窄矩形' in c.statusText
    jobs = capture_tasks(view, monkeypatch, c)
    draw(view, (25, 61), (102, 66))
    result = finish(view, jobs[-1])
    assert c.status == 'ready'
    assert set(c.currentResult) == {'ramp'}
    assert jobs[-1][1].shape == (6, 78)
    ramp = c.currentResult['ramp']
    assert ramp['thickness'] == pytest.approx(ramp['fwhm'] * np.tan(np.deg2rad(23)))
    assert c.rampAngle == 23 and '23°' in c.roiMetricLabel
    view.settingsController.setValue('services', 'rampThicknessAngle', 45)
    assert c.currentResult['ramp']['thickness'] == ramp['thickness']
    assert '23°' in c.roiMetricLabel and len(jobs) == 1
    c.recalculate()
    result = finish(view, jobs[-1])
    assert c.currentResult['ramp']['thickness'] == pytest.approx(ramp['fwhm'])
    assert '45°' in c.roiMetricLabel and len(jobs) == 2
    view.settingsController.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
    assert c.currentResult['ramp']['fwhm'] == ramp['fwhm']
    assert c._current_analysis().result is result
    view._tool_controller.selectService('service:mtf')
    assert view.mtfController.currentResult == {} and not view.mtfController.roiController.measurementItems
    draw(view, (25, 61), (102, 66))
    roi = view.mtfController.roiController.measurementItems[0]
    assert roi['metrics']['width_mm'] == pytest.approx(roi['metrics']['height_mm'])


def test_ramp_direction_change_keeps_roi_and_rejects_stale_results(mtf_viewport, monkeypatch):
    view, _ = mtf_viewport
    c = view.fwhmController
    view._tool_controller.selectService('service:fwhm')
    jobs = capture_tasks(view, monkeypatch, c)
    draw(view, (25, 25), (102, 102))
    original_job = jobs[-1]
    finish(view, original_job)
    roi = c.roiController.measurementItems
    x = c.currentResult['ramp']
    c.setRampDirection('y')
    assert c.status == 'calculating' and c.currentResult == {}
    finish(view, original_job)
    assert c.status == 'calculating'
    finish(view, jobs[-1])
    assert c.currentResult['ramp']['direction'] == 'y'
    assert c.currentResult['ramp']['fwhm'] < x['fwhm']
    assert c.roiController.measurementItems == roi
    view._tool_controller.selectService('service:mtf')
    finish(view, jobs[-1])
    assert view.mtfController.currentResult == {}
    assert c.currentResult['ramp']['direction'] == 'y'


def test_mtf_and_fwhm_keep_independent_methods_rois_results_and_reset(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    mtf, fwhm = view.mtfController, view.fwhmController
    mtf_jobs = capture_tasks(view, monkeypatch, mtf)
    fwhm_jobs = capture_tasks(view, monkeypatch, fwhm)
    assert [m['value'] for m in mtf.measurementMethods] == ['bead', 'wire']
    assert [m['value'] for m in fwhm.measurementMethods] == ['ramp']
    mtf.setMeasurementMethod('ramp')
    fwhm.setMeasurementMethod('bead')
    assert mtf.measurementMethod == 'bead' and fwhm.measurementMethod == 'ramp'
    draw(view)
    finish(view, mtf_jobs[-1])
    mtf_result = mtf.currentResult
    mtf_roi = mtf.roiController.measurementItems
    view._tool_controller.selectService('service:fwhm')
    assert view.activeAnnotationController is fwhm.roiController
    assert view.activeProfileController is fwhm
    assert view._tool_controller.resetLabel == '重置 FWHM'
    fwhm.setAnalysisMethod('direct_fft')
    draw(view, (25, 61), (102, 66))
    finish(view, fwhm_jobs[-1])
    fwhm_result = fwhm.currentResult
    fwhm_roi = fwhm.roiController.measurementItems
    assert fwhm.actualAnalysisMethod == 'half_height'
    assert mtf.analysisMethod == 'tukey_fft' and mtf.currentResult == mtf_result
    assert mtf.roiController.measurementItems == mtf_roi
    view._tool_controller.selectService('service:mtf')
    assert view.activeAnnotationController is mtf.roiController
    assert view.activeProfileController is mtf
    assert mtf.currentResult == mtf_result
    view.reset_tool_state(ToolType.SERVICE)
    assert mtf.currentResult == {} and not mtf.roiController.measurementItems
    assert fwhm.currentResult == fwhm_result and fwhm.roiController.measurementItems == fwhm_roi
    view._tool_controller.selectService('service:fwhm')
    view.apply_slice_index(1)
    deliver_frame(view, replace(frame, frame_meta=replace(frame.frame_meta, slice_index=1)))
    assert fwhm.currentResult == {} and not fwhm.roiController.measurementItems
    view.apply_slice_index(0)
    deliver_frame(view, frame)
    assert fwhm.currentResult == fwhm_result and len(fwhm_jobs) == 1
    view.deleteSelectedMeasurement()
    # Select by clicking the remaining ROI before deleting.
    draw(view, (60, 63), (60, 63))
    view.deleteSelectedMeasurement()
    assert fwhm.currentResult == {}
    assert mtf.currentResult == {}


@pytest.mark.parametrize('tab_type', [TabType.MPR, TabType.THREE_D, TabType.FOUR_D, TabType.TAG])
def test_fwhm_cannot_bypass_supported_tab_gate(tab_type):
    tools = ToolController(tab_type=tab_type)
    before = tools.activeInteraction
    tools.selectInteraction('service:fwhm')
    assert tools.activeInteraction == before


def test_small_selection_automatically_samples_background_in_worker(mtf_viewport):
    view, _ = mtf_viewport
    # Selection lacks background, but the original image contains it.
    draw(view, (10, 10), (95, 95))
    wait_result(view.mtfController)
    assert view.mtfController.status == "ready"
    assert any("自动取样" in w for w in view.mtfController.warnings)
    assert view.mtfController.currentResult["x"]["mtf10"] > 0


def test_equivalent_settings_require_explicit_recalculation(qt_app, monkeypatch):
    import math
    view = _controller()
    try:
        deliver_frame(view, bead_render(view))
        view._tool_controller.selectService('service:mtf')
        c = view.mtfController
        assert c.settingsController.section('services')['mtfGaussianEquivalent'] is True
        jobs = capture_tasks(view, monkeypatch)
        draw(view)
        measured = finish(view, jobs[-1])
        assert c.actualAnalysisMethod == 'gaussian_equivalent'
        assert '高斯等效' not in c.roiMetricLabel
        for direction in ('x', 'y'):
            axis = c.currentResult[direction]
            assert axis['mtf50'] == pytest.approx(axis['mtf10']*math.sqrt(math.log(2)/math.log(10)))
        cached = c._current_analysis().result
        c.settingsController.setValue('services', 'mtfGaussianEquivalent', False)
        assert c.actualAnalysisMethod == 'gaussian_equivalent'
        assert len(jobs) == 1
        c.recalculate()
        measured = finish(view, jobs[-1])
        assert c.actualAnalysisMethod == 'tukey_fft'
        assert c.currentResult['x']['mtf50'] == measured.x.mtf50
        assert c.currentResult['x']['mtf'] == list(measured.x.mtf)
        assert '高斯等效' not in c.roiMetricLabel
        c.settingsController.setValue('services', 'mtfGaussianEquivalent', True)
        c.recalculate()
        cached = finish(view, jobs[-1])
        c.settingsController.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
        assert c.currentResult['x']['mtf10'] == pytest.approx(measured.x.mtf10*10)
        assert c.currentResult['x']['mtf50'] == pytest.approx(measured.x.mtf10*10*math.sqrt(math.log(2)/math.log(10)))
        assert c._current_analysis().result is cached and len(jobs) == 3
        assert not view.fwhmController.currentResult
    finally:
        view.shutdown()


def test_equivalent_toggle_leaves_existing_fwhm_result_untouched(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    c = view.fwhmController
    view._tool_controller.selectService('service:fwhm')
    jobs = capture_tasks(view, monkeypatch, c)
    draw(view, (25, 61), (102, 66))
    finish(view, jobs[-1])
    result, label, method = c.currentResult, c.roiMetricLabel, c.actualAnalysisMethod
    c.settingsController.setValue('services', 'mtfGaussianEquivalent', True)
    assert c.currentResult == result and c.roiMetricLabel == label and c.actualAnalysisMethod == method
    assert len(jobs) == 1


@pytest.mark.parametrize('service', ['mtf', 'fwhm'])
def test_basic_roi_geometry_visible_while_drawing_calculating_and_failed(mtf_viewport, monkeypatch, service):
    view, _ = mtf_viewport
    view._tool_controller.selectService('service:'+service)
    c = view.mtfController if service == 'mtf' else view.fwhmController
    jobs = capture_tasks(view, monkeypatch, c)
    view.beginInteraction(0, 0, 1, True, 20, 20, .1, .1)
    view.updateInteraction(QPointF(), QPointF(50, 50), QPointF(50, 50), QPointF(50, 50), True, 80, 60)
    assert c.status == 'editing'
    assert c.roiMetricLabel == 'ROI  6.00 × 6.00 mm · 36.00 mm²'
    assert not jobs
    view.endInteraction(50, 50, True, 80, 60)
    assert c.status == 'calculating'
    assert c.roiMetricLabel == 'ROI  6.00 × 6.00 mm · 36.00 mm²'
    assert 'MTF50' not in c.roiMetricLabel and 'FWHM' not in c.roiMetricLabel
    c._receive_result(jobs[-1][0], None, '测试计算失败')
    assert c.status == 'error'
    assert c.roiMetricLabel == 'ROI  6.00 × 6.00 mm · 36.00 mm²'
    c.reset()
    assert c.roiMetricLabel == ''
