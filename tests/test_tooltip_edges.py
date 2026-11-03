"""Tooltips must not cover their trigger or compete for input at window edges."""
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_dicom_tags import qt_app, wait_until
from test_display_tools_qml import display_panel, _find
from qt_pointer import move_pointer


def tip_rect(tip, window):
    label = tip.property("contentItem")
    popup = label.window()
    position = popup.position() - window.position()
    return QRectF(position.x(), position.y(), popup.width(), popup.height())


def assert_stable_tip(window, action, button, tip):
    window.requestActivate()
    wait_until(window.isActive)
    # Close to the upper edge, where a clamped 'above' tooltip used to overlap.
    point = button.mapToScene(QPointF(button.width()/2, 2)).toPoint()
    move_pointer(window, point)
    wait_until(lambda: tip.property("visible"))
    QTest.qWait(80)
    label = tip.property("contentItem")
    popup = label.window()
    trigger = QRectF(action.mapToScene(QPointF()), action.size())
    assert not tip_rect(tip, window).intersects(trigger), (tip_rect(tip, window), trigger)
    assert popup.flags() & Qt.WindowTransparentForInput
    assert popup.flags() & Qt.WindowDoesNotAcceptFocus
    samples = []
    for _ in range(14):
        QTest.qWait(80)  # More than two tooltip delay cycles with a stationary pointer.
        samples.append((action.property("hovered"), tip.property("visible")))
    assert all(hovered and visible for hovered, visible in samples), samples


@pytest.fixture
def edge_scene(qt_app):
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    errors = []
    view.engine().warnings.connect(lambda es: errors.extend(e.toString() for e in es))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/TooltipEdges.qml")))
    assert view.status() == QQuickView.Ready, errors
    view.show()
    QTest.qWait(50)
    try:
        yield view, view.rootObject(), errors
    finally:
        view.hide()
        delete(view)


@pytest.mark.parametrize("x,y,placement", [(190, 4, "above"), (190, 240, "above"),
                                         (4, 100, "left"), (376, 100, "right"),
                                         (4, 4, "above"), (376, 240, "right")])
def test_tooltip_flips_at_edges_without_losing_hover(edge_scene, x, y, placement):
    view, root, errors = edge_scene
    root.setProperty("anchorX", x)
    root.setProperty("anchorY", y)
    root.setProperty("placement", placement)
    action = root.findChild(QObject, "edgeAction")
    button = root.findChild(QObject, "edgeButton")
    tip = root.findChild(QObject, "toolbarTooltip")
    assert_stable_tip(view, action, button, tip)
    bounds = tip_rect(tip, view)
    assert QRectF(0, 0, view.width(), view.height()).contains(bounds), bounds
    # The tooltip must not block the command or leave keyboard-focus tooltip state.
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                     button.mapToScene(QPointF(button.width()/2, 2)).toPoint())
    assert root.property("clicks") == 1
    wait_until(lambda: not tip.property("visible"))
    assert not errors, errors


def test_actual_primary_toolbar_first_row_stays_hovered(display_panel):
    view, controller, warnings = display_panel
    button = _find(view.rootObject(), "primaryTool-window")
    action = button.parentItem()
    tip = action.findChild(QObject, "toolbarTooltip")
    assert_stable_tip(view, action, button, tip)
    geometry = (button.mapToScene(QPointF()), button.size())
    for local in (QPointF(1, button.height()/2), QPointF(button.width()-1, button.height()/2),
                  QPointF(button.width()/2, 1), QPointF(button.width()/2, button.height()-1)):
        move_pointer(view, button.mapToScene(local).toPoint())
        QTest.qWait(150)
        assert action.property("hovered") and tip.property("visible")
        assert geometry == (button.mapToScene(QPointF()), button.size())
    move_pointer(view, QPoint(view.width()-2, view.height()-2))
    wait_until(lambda: not tip.property("visible"))
    assert not warnings, warnings


@pytest.mark.parametrize("enabled,text", [(False, "Unavailable for this image"),
                                           (True, "Long tooltip with wrapping " * 12)])
def test_disabled_and_wrapped_tooltips_are_passive(edge_scene, enabled, text):
    view, root, errors = edge_scene
    root.setProperty("actionEnabled", enabled)
    root.setProperty("tooltipText", text)
    action = root.findChild(QObject, "edgeAction")
    button = root.findChild(QObject, "edgeButton")
    tip = root.findChild(QObject, "toolbarTooltip")
    assert_stable_tip(view, action, button, tip)
    assert tip.property("width") <= 360
    assert QRectF(0, 0, view.width(), view.height()).contains(tip_rect(tip, view))
    move_pointer(view, QPoint(2, view.height()-2))
    wait_until(lambda: not tip.property("visible"))
    assert not errors, errors


@pytest.mark.parametrize("already_open", [True, False])
def test_tooltip_cannot_outlive_anchor_window_focus(edge_scene, already_open):
    view, root, errors = edge_scene
    view.requestActivate()
    wait_until(view.isActive)
    tip = root.findChild(QObject, "toolbarTooltip")
    button = root.findChild(QObject, "edgeButton")
    other = QQuickView()
    other.setPosition(view.x() + view.width() + 20, view.y())
    try:
        move_pointer(view, button.mapToScene(QPointF(button.width()/2, 2)).toPoint())
        if already_open:
            wait_until(lambda: tip.property("visible"))
        other.show()
        other.requestActivate()
        wait_until(lambda: other.isActive() and not view.isActive())
        QTest.qWait(tip.property("delay") + 120)
        assert not tip.property("visible")
        native = tip.property("contentItem").window()
        assert native is None or native is view or not native.isVisible()
        assert not errors, errors
    finally:
        other.hide()
        delete(other)
