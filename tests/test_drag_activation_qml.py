"""A threshold-crossing move must update the real viewport before release."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from test_measurement_qml import qt_app, viewport


@pytest.mark.parametrize("tool,button,expected", [
    ("pan", Qt.LeftButton, (120, 80, 400, 40, 1)),
    ("window", Qt.LeftButton, (0, 0, 448, -4.44, 1)),
    ("zoom", Qt.LeftButton, (0, 0, 400, 40, .8572)),
    ("pan", Qt.RightButton, (0, 0, 400, 40, .8572)),
    ("pan", Qt.MiddleButton, (120, 80, 400, 40, 1)),
])
@pytest.mark.parametrize("moves", [1, 2])
def test_drag_applies_full_displacement_once(viewport, tool, button, expected, moves):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.activateTool(tool)
    layer = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    updates = []
    layer.dragMoved.connect(lambda start, current, step, total: updates.append(
        (QPointF(current), QPointF(step), QPointF(total))))
    origin = pixels.mapToScene(QPointF())
    initial_span = pixels.mapToScene(QPointF(256, 0)) - origin
    start, end = QPoint(300, 300), QPoint(420, 380)
    QTest.mousePress(view, button, Qt.NoModifier, start)
    try:
        if moves == 2:
            QTest.mouseMove(view, QPoint(360, 340), 20)
        QTest.mouseMove(view, end, 20)
        # The activation frame itself must update the image while held.
        state = (controller.panX, controller.panY, controller.windowWidth,
                 controller.windowCenter, controller.zoom)
        assert state == pytest.approx(expected)
    finally:
        QTest.mouseRelease(view, button, Qt.NoModifier, end)
    QTest.qWait(30)
    assert (controller.panX, controller.panY, controller.windowWidth,
            controller.windowCenter, controller.zoom) == pytest.approx(expected)
    assert not controller.hasActiveDrag()
    assert updates[-1][2] == QPointF(120, 80)
    assert sum((step for _, step, _ in updates), QPointF()) == QPointF(120, 80)
    # Check the displayed image geometry, not just the controller values.
    span = pixels.mapToScene(QPointF(256, 0)) - pixels.mapToScene(QPointF())
    assert span.x() == pytest.approx(initial_span.x() * expected[4])
    if expected[0]:
        assert pixels.mapToScene(QPointF()) - origin == QPointF(120, 80)
    assert not warnings, warnings


@pytest.mark.parametrize("tool", ["pan", "window", "zoom"])
def test_click_below_drag_threshold_keeps_view_unchanged(viewport, tool):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.activateTool(tool)
    origin = pixels.mapToScene(QPointF())
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300))
    QTest.mouseMove(view, QPoint(301, 301), 20)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, QPoint(301, 301))
    assert (controller.panX, controller.panY, controller.windowWidth,
            controller.windowCenter, controller.zoom) == (0, 0, 400, 40, 1)
    assert pixels.mapToScene(QPointF()) == origin
    assert not controller.hasActiveDrag()
    assert not warnings, warnings


def test_drag_includes_motion_on_release(viewport):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.activateTool("pan")
    origin = pixels.mapToScene(QPointF())
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300))
    QTest.mouseMove(view, QPoint(360, 340), 20)
    # A coalesced final move can arrive only in the release event.
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, QPoint(420, 380))
    assert (controller.panX, controller.panY) == (120, 80)
    assert pixels.mapToScene(QPointF()) - origin == QPointF(120, 80)
    assert not controller.hasActiveDrag()
    assert not warnings, warnings
