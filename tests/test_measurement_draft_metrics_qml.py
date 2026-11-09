"""Incomplete geometry shows control points, without premature measurement labels."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_measurement_qml import qt_app, viewport, _click_points, _move_pointer, _scene, _visual_children


def metric_labels(view):
    return [item for item in _visual_children(view.rootObject())
            if item.isVisible() and item.objectName() in
            ('measurementLabel', 'roiMetricCard', 'roiCompactLabel')]


def move(view, pixels, column, row):
    _move_pointer(view, _scene(pixels, column, row))


def start(view, controller, pixels, kind):
    controller._tool_controller.selectInteraction('measure:' + kind)
    # Reset Qt's cached pointer position before starting another test window.
    move(view, pixels, 40, 40)
    _click_points(view, _scene(pixels, 40, 40))


@pytest.mark.parametrize('kind', ['length', 'angle', 'rect', 'ellipse', 'curve', 'freehand'])
def test_first_point_has_no_metrics_and_escape_removes_draft(viewport, kind):
    view, controller, pixels, warnings = viewport
    start(view, controller, pixels, kind)
    assert controller.measurementController.has_active_transaction
    assert not metric_labels(view), controller.measurementController.activeTransaction
    QTest.keyClick(view, Qt.Key_Escape)
    QTest.qWait(30)
    assert not controller.measurementController.has_active_transaction
    assert not metric_labels(view), controller.measurementController.activeTransaction
    assert not controller.measurementController.measurementItems
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length', 'rect', 'ellipse'])
def test_valid_preview_shows_metrics_and_collapsing_to_start_hides_them(viewport, kind):
    view, controller, pixels, warnings = viewport
    start(view, controller, pixels, kind)
    assert not metric_labels(view), controller.measurementController.activeTransaction
    if kind != 'length':
        move(view, pixels, 90, 40)  # A zero-height ROI is still incomplete.
        assert not metric_labels(view)
    move(view, pixels, 90, 100)
    assert len(metric_labels(view)) == 1
    assert not controller.measurementController.measurementItems
    move(view, pixels, 40, 40)
    assert not metric_labels(view)
    _click_points(view, _scene(pixels, 90, 100))
    assert len(controller.measurementController.measurementItems) == 1
    assert len(metric_labels(view)) == 1
    assert not warnings, warnings


def test_angle_waits_for_both_arms_before_showing_a_value(viewport):
    view, controller, pixels, warnings = viewport
    start(view, controller, pixels, 'angle')
    move(view, pixels, 90, 40)
    assert not metric_labels(view)
    _click_points(view, _scene(pixels, 90, 40))
    assert not metric_labels(view)
    move(view, pixels, 90, 100)
    label, = metric_labels(view)
    assert label.property('text') == '90.00°'
    _click_points(view, _scene(pixels, 90, 100))
    assert len(controller.measurementController.measurementItems) == 1
    assert len(metric_labels(view)) == 1
    assert not warnings, warnings


def test_curve_length_starts_with_two_confirmed_points(viewport):
    view, controller, pixels, warnings = viewport
    start(view, controller, pixels, 'curve')
    move(view, pixels, 90, 40)
    assert not metric_labels(view)  # Hover alone does not extend the measured curve.
    _click_points(view, _scene(pixels, 90, 40))
    label, = metric_labels(view)
    assert 'mm' in label.property('text')
    assert not controller.measurementController.measurementItems
    _click_points(view, _scene(pixels, 90, 100))
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(30)
    assert len(controller.measurementController.measurementItems) == 1
    assert len(metric_labels(view)) == 1
    assert not warnings, warnings
