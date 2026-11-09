"""Real pointer edits cross the image edge and restore valid statistics."""
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_measurement_qml import qt_app, viewport, _scene, _click_points, _mouse_drag, _visual_children


def shown(view, name):
    return [i for i in _visual_children(view.rootObject()) if i.objectName() == name and i.isVisible()]


@pytest.mark.parametrize('kind', ['rect','ellipse','freehand'])
def test_roi_partial_to_empty_and_back_preserves_geometry_and_updates_card(viewport, kind):
    view, c, pixels, warnings = viewport
    c.apply_zoom(.5)
    c._tool_controller.selectInteraction('measure:' + kind)
    points = [(-30, 40), (50, 100)] if kind != 'freehand' else [(-30, 40), (50, 40), (50, 100), (-30, 100)]
    _click_points(view, *[_scene(pixels, *p) for p in points])
    if kind == 'freehand':
        QTest.keyClick(view, Qt.Key_Return)
    measure = c.measurementController
    assert len(measure.measurementItems) == 1
    original = measure.measurementItems[0]
    assert original['metrics']['pixel_count'] > 0
    assert np.isfinite([original['metrics'][key] for key in ['mean','std','minimum','maximum']]).all()
    assert original['metrics']['width_mm'] > 75  # Preserve the part outside the image.
    assert not shown(view, 'roiNoValidSamples')
    # Drag the outline, not the label. Translate the entire shape outside the image.
    start = _scene(pixels, 50, 70)
    end = _scene(pixels, -100, 70)
    _mouse_drag(view, start, end)
    empty = measure.measurementItems[0]
    assert empty['metrics']['pixel_count'] == 0
    assert empty['metrics']['mean'] is None
    assert empty['metrics']['area_mm2'] == pytest.approx(original['metrics']['area_mm2'], rel=.03)
    card, = shown(view, 'roiMetricCard')
    status, = shown(view, 'roiNoValidSamples')
    assert status.property('text') == '无有效像素'
    assert not any(i.isVisible() and i.property('text') in ['Mean','SD','Min','Max'] for i in _visual_children(card))
    _mouse_drag(view, end, start)
    restored = measure.measurementItems[0]
    assert restored['metrics']['pixel_count'] > 0
    assert restored['metrics']['mean'] == pytest.approx(original['metrics']['mean'], abs=1)
    assert restored['metrics']['area_mm2'] == pytest.approx(original['metrics']['area_mm2'], rel=.03)
    assert not shown(view, 'roiNoValidSamples')
    assert not warnings, warnings


@pytest.mark.parametrize('primary_valid,secondary_valid,message', [
    (False, True, 'PET: 无有效像素'),
    (True, False, 'CT: 无有效像素'),
    (False, False, '无有效像素'),
    (True, True, ''),
])
def test_fusion_card_keeps_valid_modality_statistics_and_respects_visibility(
    viewport, primary_valid, secondary_valid, message
):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.selectInteraction('measure:rect')
    _click_points(view, _scene(pixels, 40, 40), _scene(pixels, 90, 90))
    measurement = controller.measurementController.measurementItems[0]
    metrics = measurement['metrics']
    empty = dict(metrics, pixel_count=0, mean=None, std=None, minimum=None, maximum=None)
    card, = shown(view, 'roiMetricCard')
    card.setProperty('measurement', dict(
        measurement,
        metrics=metrics if primary_valid else empty,
        secondaryMetrics=metrics if secondary_valid else empty,
    ))
    QTest.qWait(30)
    status = shown(view, 'roiNoValidSamples')
    assert [item.property('text') for item in status] == ([message] if message else [])
    labels = {item.property('text') for item in _visual_children(card) if item.isVisible() and item.property('text')}
    assert ('Mean' in labels) == primary_valid
    assert ('CT Mean' in labels) == secondary_valid
    card.setProperty('visibleMetrics', dict.fromkeys(['mean', 'std', 'minimum', 'maximum', 'count'], False))
    QTest.qWait(30)
    assert not shown(view, 'roiNoValidSamples')
    assert not warnings, warnings
