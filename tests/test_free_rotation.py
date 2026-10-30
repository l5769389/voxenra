"""In-plane display rotation must never alter slice geometry or pixel measurements."""
from math import cos, radians, sin

import pytest
from PySide6.QtCore import QPointF

from qt_dicom_viewer.model import TabType, ToolType
from test_dicom_tags import qt_app
from test_viewport_transform import _controller, _render_result


def drag_arc(view, start_angle, end_angle, *, center=(200, 200), radius=100):
    def point(angle):
        return QPointF(center[0] + radius * cos(radians(angle)),
                       center[1] + radius * sin(radians(angle)))
    start, end = point(start_angle), point(end_angle)
    view.beginInteraction(start.x(), start.y(), 1, True, 0, 0, .05, .05)
    view.updateInteraction(start, end, end - start, end - start, True, 0, 0)
    view.endInteraction(end.x(), end.y(), True, 0, 0)


@pytest.mark.parametrize("mirrored", [False, True])
def test_rotate_tool_drags_image_and_one_shot_actions_keep_the_mode(qt_app, mirrored):
    view = _controller(tab_type=TabType.TWO_D)
    result = _render_result(view)
    view.handleRenderResult(result)
    view.setViewportSize(400, 400)
    view.apply_pan(20, -10)
    view.apply_zoom(2)
    if mirrored:
        view.applyTransformAction("rotate:mirror-h")
    tools = view._tool_controller
    tools.activateTool("rotate")
    renders = []
    view.renderRequested.connect(renders.append)
    original_geometry = view._frame_meta.geometry
    drag_arc(view, 0, 30, center=(220, 190))
    assert view.rotationDegrees == pytest.approx(30)
    view.applyTransformAction("rotate:cw90")
    assert view.rotationDegrees == pytest.approx(120)
    assert tools.activeInteraction == "rotate"
    drag_arc(view, 0, -15, center=(220, 190))
    assert view.rotationDegrees == pytest.approx(105)
    assert view.horizontalFlip == mirrored
    assert view._frame_meta.geometry == original_geometry
    assert not renders  # Pure display transformation, no reslicing.
    view.handleRenderResult(result)
    assert view.rotationDegrees == pytest.approx(105)
    view.reset_tool_state(ToolType.ROTATE)
    assert view.rotationDegrees == 0
    assert view.panX == 20 and view.panY == -10 and view.zoom == 2
    tools.activateTool("pan")
    drag_arc(view, 0, 30, center=(220, 190))
    assert view.rotationDegrees == 0


def test_free_rotation_preserves_measurements_and_reopens_with_tool(qt_app):
    view = _controller(tab_type=TabType.TWO_D)
    view.handleRenderResult(_render_result(view))
    view.setViewportSize(400, 400)
    tools = view._tool_controller
    tools.selectInteraction("measure:rect")
    view.beginInteraction(0, 0, 1, True, -.5, -.5, .05, .05)
    view.endInteraction(10, 10, True, 1.5, 1.5)
    measurements = view.measurementController.measurementItems
    assert measurements
    tools.activateTool("rotate")
    drag_arc(view, 170, -170)
    assert view.rotationDegrees == pytest.approx(20)
    assert view.measurementController.measurementItems == measurements
    saved_selection = tools.persistent_selection()
    tools.activateTool("pan")
    tools.restore_selection(saved_selection)
    drag_arc(view, 0, 17.5)
    assert view.rotationDegrees == pytest.approx(37.5)


def test_drag_near_center_does_not_flip_or_jump(qt_app):
    view = _controller(tab_type=TabType.TWO_D)
    view.handleRenderResult(_render_result(view))
    view.setViewportSize(400, 400)
    view._tool_controller.activateTool("rotate")
    view.beginInteraction(300, 200, 1, True, 0, 0, .05, .05)
    for x, y in [(201, 200), (200, 200), (100, 200)]:
        view.updateInteraction(QPointF(300, 200), QPointF(x, y), QPointF(),
                               QPointF(x - 300, y - 200), True, 0, 0)
        assert view.rotationDegrees == 0
    view.updateInteraction(QPointF(300, 200), QPointF(200, 100), QPointF(),
                           QPointF(-100, -100), True, 0, 0)
    assert view.rotationDegrees == pytest.approx(90)
    view.endInteraction(200, 100, True, 0, 0)


def test_fast_drag_across_center_does_not_flip(qt_app):
    view = _controller(tab_type=TabType.TWO_D)
    view.handleRenderResult(_render_result(view))
    view.setViewportSize(400, 400)
    view._tool_controller.activateTool("rotate")
    view.beginInteraction(300, 200, 1, True, 0, 0, .05, .05)
    view.updateInteraction(QPointF(300, 200), QPointF(100, 201), QPointF(-200, 1),
                           QPointF(-200, 1), True, 0, 0)
    assert view.rotationDegrees == 0
    view.endInteraction(100, 201, True, 0, 0)


def test_montage_rotate_button_uses_the_same_drag_behavior(qt_app):
    from test_montage_controller import _controller as montage_controller
    view = montage_controller()
    view._tool_controller.activateTool("rotate")
    view.beginInteraction(300, 200, 1, 400, 400)
    start, end = QPointF(300, 200), QPointF(300, 300)
    view.updateInteraction(start, end, end - start, end - start)
    view.endInteraction(end.x(), end.y())
    assert view.rotationDegrees == pytest.approx(45)
    view.applyTransformAction("rotate:ccw90")
    assert view.rotationDegrees == pytest.approx(315)


@pytest.mark.parametrize("tab_type", ["2d", "mpr"])
def test_saved_workspace_keeps_free_angle_and_rotation_mode(qt_app, tmp_path, tab_type):
    from test_workspace_persistence import populated_app, wait_until
    app, record = populated_app(tmp_path)
    try:
        if tab_type == "mpr":
            app.workspaceController.createTab(record.series_instance_uid, "MPR", "mpr")
            wait_until(lambda: app.workspaceController.activeViewport.loadState == "ready")
        view = app.workspaceController.activeViewport
        view.setViewportSize(400, 400)
        view._tool_controller.activateTool("rotate")
        drag_arc(view, 0, 37.5)
        assert view.rotationDegrees == pytest.approx(37.5)
        original_mpr = getattr(view, "_mpr_state", None)
        path = tmp_path / "rotation.voxworkspace"
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        restored = app.workspaceController.activeViewport
        assert restored is not view
        assert restored.rotationDegrees == pytest.approx(37.5)
        assert restored.activeInteraction == "rotate"
        assert getattr(restored, "_mpr_state", None) == original_mpr
    finally:
        app.shutdown()

