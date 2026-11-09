"""Rendered overlays must remain readable after image transforms."""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from test_measurement_qml import qt_app, viewport, _scene, _click_points, _mouse_drag, _visual_children


def visible(view, name):
    return [i for i in _visual_children(view.rootObject())
            if i.isVisible() and i.objectName().startswith(name)]


def bounds(item):
    return QRectF(item.mapToScene(QPointF()), item.size())


def corner_ink(view):
    result = []
    for line in visible(view, 'cornerInformationLine'):
        if not line.property('text'):
            continue
        rect = bounds(line)
        width = min(rect.width(), line.property('implicitWidth'))
        if line.parentItem().parentItem().objectName().endswith('Right'):
            rect.setLeft(rect.right() - width)
        else:
            rect.setWidth(width)
        result.append(rect)
    assert result
    return result


def assert_clear(view, label):
    rect = bounds(label)
    assert QRectF(0, 0, view.width(), view.height()).contains(rect)
    assert not any(rect.intersects(r) for r in corner_ink(view)), (rect, corner_ink(view))


@pytest.mark.parametrize('expanded', [False, True])
@pytest.mark.parametrize('width', [1000, 480])
def test_zoomed_roi_avoids_metadata(viewport, expanded, width):
    view, c, pixels, warnings = viewport
    view.resize(width, 720)
    QTest.qWait(30)
    c._tool_controller.selectInteraction('measure:rect')
    _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    if not expanded:
        c.measurementController.clear_selection()
    original = c.measurementController.measurementItems[0]['points']
    c.apply_zoom(3)
    c.apply_pan(750, -550)
    QTest.qWait(60)
    label, = visible(view, 'roiMetricCard' if expanded else 'roiCompactLabel')
    assert_clear(view, label)
    assert c.measurementController.measurementItems[0]['points'] == original
    assert not warnings, warnings


def test_manual_label_keeps_saved_position_but_avoids_corners_when_zoomed(viewport):
    view, c, pixels, warnings = viewport
    c._tool_controller.selectInteraction('measure:rect')
    _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    card, = visible(view, 'roiMetricCard')
    start = card.mapToScene(QPointF(card.width()/2, card.height()/2)).toPoint()
    _mouse_drag(view, start, QPoint(150, 540))
    saved = dict(c.measurementController.measurementItems[0]['labelPosition'])
    initial = bounds(visible(view, 'roiMetricCard')[0])
    c.apply_zoom(3)
    QTest.qWait(60)
    assert_clear(view, visible(view, 'roiMetricCard')[0])
    assert c.measurementController.measurementItems[0]['labelPosition'] == saved
    c.apply_zoom(1)
    QTest.qWait(60)
    assert bounds(visible(view, 'roiMetricCard')[0]) == initial
    assert not warnings, warnings


def test_zoomed_annotation_avoids_patient_information(viewport):
    view, c, pixels, warnings = viewport
    c._tool_controller.activateTool('annotate')
    c.setAnnotationMode(True)
    c.textAnnotationController.setAnnotationText('Audit annotation')
    _click_points(view, _scene(pixels, 170, 60), _scene(pixels, 130, 90))
    original = c.textAnnotationController.annotationItems
    c.apply_zoom(3)
    c.apply_pan(750, -550)
    QTest.qWait(60)
    label, = visible(view, 'annotationLabel-')
    assert_clear(view, label)
    assert c.textAnnotationController.annotationItems == original
    assert not warnings, warnings


def test_curve_instruction_does_not_cover_scale(viewport):
    view, c, pixels, warnings = viewport
    c.setViewportSetting('scale-bar', True)
    c._tool_controller.selectInteraction('measure:curve')
    _click_points(view, _scene(pixels, 100, 110))
    instruction = c.measurementController.instruction
    assert instruction
    text, = [i for i in _visual_children(view.rootObject())
             if i.isVisible() and i.property('text') == instruction]
    scale, = visible(view, 'scaleBarLabel')
    assert not bounds(text).intersects(bounds(scale)), (bounds(text), bounds(scale))
    assert not warnings, warnings


def test_corner_fallback_does_not_stack_roi_labels(viewport):
    view, c, pixels, warnings = viewport
    c._tool_controller.selectInteraction('measure:rect')
    for a, b in [((30, 35), (60, 65)), ((110, 120), (140, 150))]:
        _click_points(view, _scene(pixels, *a), _scene(pixels, *b))
        c.measurementController.clear_selection()
    c.apply_zoom(3)
    c.apply_pan(-750, -550)
    QTest.qWait(60)
    first, second = visible(view, 'roiCompactLabel')
    assert_clear(view, first)
    assert_clear(view, second)
    assert not bounds(first).intersects(bounds(second))
    assert not warnings, warnings


def test_annotation_fallback_avoids_measurement_label(viewport):
    view, c, pixels, warnings = viewport
    c._tool_controller.selectInteraction('measure:rect')
    _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    c.measurementController.clear_selection()
    c._tool_controller.activateTool('annotate')
    c.setAnnotationMode(True)
    c.textAnnotationController.setAnnotationText('Audit annotation')
    _click_points(view, _scene(pixels, 170, 60), _scene(pixels, 130, 90))
    c.apply_zoom(3)
    c.apply_pan(750, -550)
    QTest.qWait(60)
    label, = visible(view, 'annotationLabel-')
    roi, = visible(view, 'roiCompactLabel')
    assert not bounds(label).intersects(bounds(roi))
    assert not warnings, warnings


def test_reserved_metadata_measures_literal_text(viewport):
    view, c, pixels, warnings = viewport
    corner, = visible(view, 'overlay-topRight')
    corner.setProperty('text', '<b>Audit patient</b>')
    QTest.qWait(30)
    line, = [i for i in _visual_children(corner)
             if i.objectName() == 'cornerInformationLine' and i.isVisible()]
    assert corner.property('inkWidth') == pytest.approx(min(line.width(), line.implicitWidth()))
    assert not warnings, warnings
