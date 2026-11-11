"""Mouse fallback behavior, specific bindings and real QML pointer routing."""
from dataclasses import replace
import os

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QCoreApplication
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from voxplane.model import InteractionType, MprFrame, MprPlane, TabType, WindowLevel
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.mpr_viewport_controller import MprViewportController
from test_measurement_qml import qt_app, viewport, _scene
from test_viewport_transform import _controller, _render_result
from test_viewport_controller_hierarchy import _viewport_config, _mpr_result
from test_montage_controller import _controller as montage_controller
from test_pet_fusion import paired_series
from test_pet_volume import fusion_scene
from test_volume_view import volume
from test_volume_display import loaded_tab


def drag(controller, button, column=1, row=1):
    start, end = QPointF(100, 150), QPointF(130, 100)
    controller.setViewportSize(600, 400)
    controller.beginInteraction(start.x(), start.y(), button, True, column, row, .1, .1)
    controller.updateInteraction(start, end, end-start, end-start, True, column+.3, row+.3)
    controller.endInteraction(end.x(), end.y(), True, column+.3, row+.3)


@pytest.mark.parametrize("modality", ["CT", "MR"])
@pytest.mark.parametrize("tool", ["window", "scroll", "pan", "zoom", "measure:length", "measure:angle",
                                  "measure:rect", "measure:ellipse", "annotate:arrow", "annotate:text",
                                  "service:mtf", "service:qa"])
def test_right_drag_zooms_without_switching_tool_or_modifying_pixels(qt_app, modality, tool):
    c = _controller()
    c.viewport_config = replace(c.viewport_config, series_meta=replace(c.viewport_config.series_meta, modality=modality))
    result = _render_result(c)
    c.handleRenderResult(result)
    c._tool_controller.selectInteraction(tool)
    before, window, pixels = c.viewport_state, c.current_window, result.modality_pixel.copy()
    try:
        drag(c, 2)
        assert c.zoom != before.zoom
        assert c.current_window == window
        assert (c.panX, c.panY, c.viewport_state.slice_index) == (before.pan_x, before.pan_y, before.slice_index)
        assert c.activeInteraction == tool
        assert c.measurementController.measurementItems == []
        np.testing.assert_array_equal(result.modality_pixel, pixels)
    finally:
        c.shutdown()


def test_right_zoom_preserves_unfinished_angle(qt_app):
    c = _controller()
    c.handleRenderResult(_render_result(c))
    c._tool_controller.selectInteraction("measure:angle")
    try:
        c.selectMeasurementAt(True, 0, 0, .1, .1)
        assert c.measurementController.has_active_transaction
        drag(c, 2)
        assert c.measurementController.has_active_transaction
        c.selectMeasurementAt(True, 1, 0, .1, .1)
        c.selectMeasurementAt(True, 1, 1, .1, .1)
        assert len(c.measurementController.measurementItems) == 1
    finally:
        c.shutdown()


@pytest.mark.parametrize("tool,changed", [("", "window"), ("window", "window"), ("pan", "pan"),
                                          ("zoom", "zoom"), ("service:qa", "window")])
def test_left_drag_uses_selected_operation_or_window_fallback(qt_app, tool, changed):
    c = _controller()
    c.handleRenderResult(_render_result(c))
    c._tool_controller.selectInteraction(tool)
    before, window = c.viewport_state, c.current_window
    try:
        drag(c, 1)
        assert (c.current_window != window) == (changed == "window")
        assert (c.panX != before.pan_x) == (changed == "pan")
        assert (c.zoom != before.zoom) == (changed == "zoom")
        assert c.activeInteraction == tool
    finally:
        c.shutdown()


@pytest.mark.parametrize("tool", ["window", "pan", "measure:rect", "mpr:rotate3d"])
def test_mpr_crosshair_left_priority_and_right_zoom(qt_app, tool):
    tools = ToolController(tab_type=TabType.MPR)
    c = MprViewportController(_viewport_config(MprPlane.AXIAL), tools)
    c.handleRenderResult(_mpr_result(c, MprFrame.standard_lps((10, 20, 30))))
    tools.selectInteraction(tool)
    centers = []
    c.crosshairCenterChangeRequested.connect(centers.append)
    try:
        window = c.current_window
        drag(c, 1, 0, 0)
        assert centers and c.zoom == 1 and c.current_window == window
        centers.clear()
        drag(c, 2, 0, 0)
        assert not centers and c.zoom != 1 and c.current_window == window
        assert c.activeInteraction == tool and not c.measurementController.measurementItems
    finally:
        c.shutdown()


@pytest.mark.parametrize("role", ["ct", "pet", "fusion", "mip"])
@pytest.mark.parametrize("tool", ["ct-window", "pet-window", "measure"])
def test_fusion_right_zoom_does_not_change_modality_window(fusion_scene, role, tool):
    _, source, _, _ = fusion_scene
    c = next(v for v in source.viewports_by_id.values() if v.viewportRole == role)
    source.toolController.activateTool(tool)
    window, ct_window, matrix = c.current_window, source._ct_window, source.matrix.copy()
    center = c.crosshairImagePosition
    drag(c, 2, center.x(), center.y())
    assert c.zoom != 1
    assert c.current_window == window and source._ct_window == ct_window
    assert c._fusion_window_target is None
    assert not c.measurementController.measurementItems
    np.testing.assert_array_equal(source.matrix, matrix)


def test_registration_right_rotation_precedes_zoom(fusion_scene):
    _, source, _, _ = fusion_scene
    c = next(v for v in source.viewports_by_id.values() if v.viewportRole == "fusion")
    source.setRegistrationActive(True)
    matrix, zoom = source.matrix.copy(), c.zoom
    c.beginInteraction(100, 100, 2, True, .5, .5, .02, .01)
    assert c.updateRegistrationDrag(.5, 1.5)
    c.endInteraction(100, 150, True, .5, 1.5)
    assert c.zoom == zoom and not np.allclose(source.matrix[:3, :3], matrix[:3, :3])


@pytest.mark.parametrize("tool", ["window", "pan", "zoom"])
def test_montage_right_drag_is_zoom(qt_app, tool):
    c = montage_controller()
    c._baseline_window = WindowLevel(40, 400)
    c._state = replace(c.viewport_state, window=c._baseline_window)
    c._tool_controller.selectInteraction(tool)
    before = c.viewport_state
    try:
        c.beginInteraction(50, 100, 2, 200, 200)
        start, end = QPointF(50, 100), QPointF(90, 50)
        c.updateInteraction(start, end, end-start, end-start)
        c.endInteraction(end.x(), end.y())
        assert c.zoom != before.zoom and c.viewport_state.window == before.window
        assert (c.panX, c.panY) == (0, 0)
        assert c.activeInteraction == tool
    finally:
        c.shutdown()


@pytest.mark.parametrize("tool", ["volume-rotate", "volume-crop", "window", "pan"])
def test_volume_right_drag_zoom_preserves_active_tool_and_crop(loaded_tab, tool):
    c, tools = loaded_tab.activeViewport, loaded_tab.toolController
    tools.activateTool(tool)
    state, display = c.state, c.display_state
    try:
        c.begin_drag((100, 100), (600, 400), 2)
        c.update_drag((140, 50))
        c.end_drag()
        assert c.state.zoom != state.zoom
        assert c.state.rotation == state.rotation and c.state.pan == state.pan
        assert c.display_state == display
        assert not c.selection_points and not c.editBusy
        assert tools.activeTool == tool
    finally:
        loaded_tab.dispose()


@pytest.mark.parametrize("tool", ["window", "pan", "measure:rect", "annotate:text"])
def test_real_right_drag_cursor_and_wheel_with_active_tool(viewport, tool):
    window, c, pixels, warnings = viewport
    c._tool_controller.selectInteraction(tool)
    c._state = replace(c.viewport_state, slice_index=3, slice_count=8)
    layer = window.rootObject().findChild(type(pixels), "viewportInteractionLayer")
    start = _scene(pixels, 70, 80)
    end = start + QPoint(45, -65)
    before_window, before_zoom = c.current_window, c.zoom
    QTest.mousePress(window, Qt.RightButton, Qt.NoModifier, start)
    QTest.mouseMove(window, (start+end)/2, 25)
    QTest.mouseMove(window, end, 25)
    QTest.qWait(30)
    assert layer.property("effectiveCursorKind") == "zoom"
    assert c.zoom != before_zoom and c.current_window == before_window
    QTest.mouseRelease(window, Qt.RightButton, Qt.NoModifier, end)
    QTest.qWait(30)
    assert c.activeInteraction == tool and not c.measurementController.measurementItems
    event = QWheelEvent(QPointF(end), QPointF(window.mapToGlobal(end)), QPoint(), QPoint(0, -120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, event)
    QTest.qWait(30)
    assert c.viewport_state.slice_index == 4
    assert c.activeInteraction == tool and c.zoom != before_zoom
    assert not warnings, warnings


@pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") == "offscreen", reason="Native QVTK canvas")
def test_native_volume_canvas_routes_right_drag_and_keeps_left_rotation(qt_app, loaded_tab):
    from unittest.mock import Mock
    from voxplane.ui.volume_viewport_host import VolumeViewportHost
    c = loaded_tab.activeViewport
    host = VolumeViewportHost(c, backend_factory=lambda widget: Mock())
    host.resize(600, 400)
    host.stack.setCurrentWidget(host.vtk_widget)
    host.show()
    QTest.qWait(80)
    canvas = host.vtk_widget
    try:
        initial = c.state
        start, end = QPoint(180, 240), QPoint(240, 150)
        QTest.mousePress(canvas, Qt.RightButton, Qt.NoModifier, start)
        QTest.mouseMove(canvas, end, 25)
        assert c._drag[-1] == InteractionType.ZOOM
        QTest.mouseRelease(canvas, Qt.RightButton, Qt.NoModifier, end)
        assert c.state.zoom != initial.zoom
        assert c.state.rotation == initial.rotation and c.state.pan == initial.pan
        assert c.activeInteraction == "volume:rotate"
        assert c._drag is None
        before = c.state
        QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(canvas, end, 25)
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, end)
        assert c.state.rotation != before.rotation and c.state.zoom == before.zoom
    finally:
        host.dispose()
        loaded_tab.dispose()


def test_real_angle_can_finish_after_temporary_right_zoom(viewport):
    from test_dicom_tags import wait_until
    window, c, pixels, warnings = viewport
    c._tool_controller.selectInteraction("measure:angle")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(pixels, 55, 55))
    # A point click is committed once Qt can distinguish it from double-click to finish.
    wait_until(lambda: c.measurementController.has_active_transaction)
    start = _scene(pixels, 80, 80)
    end = start + QPoint(35, -50)
    QTest.mousePress(window, Qt.RightButton, Qt.NoModifier, start)
    QTest.mouseMove(window, (start+end)/2, 20)
    QTest.mouseMove(window, end, 20)
    QTest.mouseRelease(window, Qt.RightButton, Qt.NoModifier, end)
    QTest.qWait(30)
    assert c.zoom != 1 and c.measurementController.has_active_transaction
    for column, row in [(110, 55), (110, 110)]:
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(pixels, column, row))
        QTest.qWait(30)
    wait_until(lambda: len(c.measurementController.measurementItems) == 1)
    assert not c.measurementController.has_active_transaction
    assert c.activeInteraction == "measure:angle"
    assert not warnings, warnings
