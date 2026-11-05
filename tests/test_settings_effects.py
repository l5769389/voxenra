"""Actual measurement rendering and settings round trips, including existing items."""
from copy import deepcopy
import json

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from qt_dicom_viewer.settings.preferences import DEFAULTS, normalize_settings
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import wait_until
from test_measurement_qml import qt_app, viewport, _scene, _click_points, _visual_children
from test_pacs_qml import scene
from test_settings_redesign import open_page
from test_tag_qml import find, click, type_text, descendants


def visible(root, name):
    return next(i for i in _visual_children(root) if i.objectName() == name and i.isVisible())


def paths(root):
    return [i for i in root.findChildren(QObject) if i.metaObject().className() == 'QQuickShapePath']


@pytest.mark.parametrize('kind', ['length', 'angle', 'rect', 'ellipse'])
def test_measurement_settings_update_existing_geometry_and_labels(viewport, kind, tmp_path):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.selectInteraction('measure:' + kind)
    if kind == 'angle':
        for point in [(30, 35), (95, 35), (95, 95)]:
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(pixels, *point))
        wait_until(lambda: bool(controller.measurementController.measurementItems))
    else:
        _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    saved = deepcopy(controller.measurementController.measurementItems)
    settings = controller.settingsController
    for key, value in {'editingColor': '#e55555', 'completedColor': '#55cc99', 'lineWidth': 4,
                       'fontSize': 18, 'editingDash': False, 'completedDash': True}.items():
        assert settings.setValue('measurement', key, value)
    QTest.qWait(50)
    item = visible(view.rootObject(), 'measurementItem')
    geometry = next(i for i in _visual_children(item) if i.isVisible() and i.property('styleSettings') is not None)
    color_key = 'measurementColor' if kind == 'length' else 'lineColor'
    assert geometry.property('isSelected') and not geometry.property('isDraft')
    assert geometry.property(color_key).name() == '#55cc99'
    assert geometry.property('dashed')
    colored = [p for p in paths(geometry) if p.property('strokeColor') == QColor('#55cc99')]
    assert colored and all(p.property('strokeWidth') == 4 for p in colored)
    if kind in ('length', 'angle'):
        assert visible(item, 'measurementLabel').property('font').pixelSize() == 18
    else:
        card = visible(item, 'roiMetricCard')
        assert card.property('metricFontSize') == 18
        size = visible(card, 'roiGeometry-dimensions')
        area = visible(card, 'roiGeometry-area')
        # 尺寸行右侧堆叠：上为长宽、下为面积，两行共用右缘。
        assert area.y() >= size.y() + size.height()
        assert size.x() == pytest.approx(area.x())
        texts = [i for i in _visual_children(card) if i.isVisible() and i.property('text')]
        assert texts and all(i.property('font').pixelSize() == 18 for i in texts)
    frame = view.grabWindow()
    assert sum(abs(frame.pixelColor(x, y).red()-85) < 15
               and abs(frame.pixelColor(x, y).green()-204) < 15
               for x in range(frame.width()) for y in range(frame.height())) > 50
    controller.measurementController.clear_selection()
    QTest.qWait(40)
    assert geometry.property(color_key).name() == '#55cc99'
    assert geometry.property('dashed')
    assert controller.measurementController.measurementItems == saved
    assert view.grabWindow().save(str(tmp_path / f'measurement-{kind}.png'))
    assert not warnings, warnings


def test_global_arrow_styles_reach_all_existing_annotations_and_preserve_local_edits(viewport):
    view, controller, pixels, warnings = viewport
    annotations = controller.textAnnotationController
    annotations.addAnnotation(30, 30, 80, 50)
    annotations.addAnnotation(100, 100, 150, 130)
    annotations.clearSelection()
    identifiers = [item['annotationId'] for item in annotations.annotationItems]
    positions = [(i['tailRow'], i['headColumn']) for i in annotations.annotationItems]
    settings = controller.settingsController
    for key, value in {'annotationColor': '#ef4444', 'fontSize': 20, 'annotationSize': 24,
                       'lineWidth': 4, 'completedDash': True}.items():
        assert settings.setValue('measurement', key, value)
    QTest.qWait(60)
    assert all(i['color'] == '#ef4444' and i['fontSize'] == 20 for i in annotations.annotationItems)
    for identifier in identifiers:
        arrow = visible(view.rootObject(), 'textAnnotation-' + identifier)
        assert arrow.property('arrowHeadLength') == 24
        strokes = paths(arrow)
        assert strokes and all(p.property('strokeWidth') == 4 for p in strokes)
        assert QQmlExpression(QQmlEngine.contextForObject(strokes[0]), strokes[0], 'Number(strokeStyle)').evaluate()[0] == 2  # ShapePath.DashLine
    # Editing a local arrow is preserved when only unrelated global line width changes.
    annotations.selectAnnotation(identifiers[0])
    annotations.setAnnotationColor('#a855f7')
    annotations.setAnnotationFontSize(26)
    settings.setValue('measurement', 'lineWidth', 3)
    assert annotations.annotationItems[0]['color'] == '#a855f7'
    assert annotations.annotationItems[0]['fontSize'] == 26
    settings.setValue('measurement', 'annotationSize', 10)
    assert annotations.annotationItems[0]['fontSize'] == 26
    settings.setValue('measurement', 'fontSize', 16)
    assert all(i['fontSize'] == 16 for i in annotations.annotationItems)
    assert [(i['tailRow'], i['headColumn']) for i in annotations.annotationItems] == positions
    assert not warnings, warnings


@pytest.mark.parametrize('legacy', [{'width': False, 'height': True}, {'width': True, 'height': False}, {'width': True, 'height': True}])
def test_roi_dimension_migration_toggle_and_reload(tmp_path, legacy):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'roi': legacy}))
    settings = SettingsController(path=path)
    assert settings.values['roi']['dimensions'] == all(legacy.values())
    assert not {'width', 'height'} & settings.values['roi'].keys()
    assert settings.setValue('roi', 'dimensions', False)
    assert settings.setValue('roi', 'dimensions', True)
    assert SettingsController(path=path).values['roi']['dimensions']
    assert not {'width', 'height'} & json.loads(path.read_text())['roi'].keys()
    assert settings.setValue('roi', 'width', False)  # compatibility maps either legacy key to the pair
    assert not settings.values['roi']['dimensions']
    assert settings.resetSection('roi') and settings.values['roi'] == DEFAULTS['roi']
    assert normalize_settings({'roi': {**legacy, 'dimensions': True}})['roi']['dimensions']


def test_roi_single_dimension_toggle_changes_preview_and_live_card(scene, tmp_path):
    from test_series_sidebar import phantom_series
    from test_dicom_tags import wait_until
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, warnings = scene
    series = phantom_series(tmp_path, 1, 'DEMO-A', '1.2.3.901', '20260907')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None and bool(app.workspaceController.activeViewport.imageSource))
    controller = app.workspaceController.activeViewport
    controller._tool_controller.selectInteraction('measure:rect')
    pixels = find(window, 'dicomPixelLayer')
    _click_points(window, _scene(pixels, 30, 35), _scene(pixels, 55, 60))
    assert controller.measurementController.measurementItems
    image_tab_id = app.workspaceController.activeTabId
    open_page(scene, 'roi')
    names = [i.objectName() for i in descendants(window.contentItem()) if i.isVisible()]
    assert 'setting-roi-dimensions' in names and 'setting-roi-width' not in names and 'setting-roi-height' not in names
    size = find(window, 'roiGeometry-dimensions')
    area = find(window, 'roiGeometry-area')
    label = find(window, 'roiGeometryLabel')
    stack = size.parentItem()
    # 尺寸标签居左，右侧同一列内上下堆叠长宽与面积。
    assert stack is area.parentItem()
    assert label.mapToScene(QPointF()).x() + label.width() <= size.mapToScene(QPointF()).x() + 1
    assert area.y() >= size.y() + size.height()
    assert size.x() == pytest.approx(area.x())
    assert max(size.x() + size.width(), area.x() + area.width()) <= stack.width() + .5
    assert window.grabWindow().save(str(tmp_path / 'roi-settings.png'))
    click(window, find(window, 'setting-roi-dimensions'))
    assert not app.settingsController.values['roi']['dimensions']
    assert not any(i.isVisible() and i.objectName() == 'roiGeometry-dimensions' for i in descendants(window.contentItem()))
    click(window, find(window, 'workspaceTab-' + image_tab_id))
    card = find(window, 'roiMetricCard')
    assert [r['key'] for r in card.property('geometryRows').toVariant()] == ['area']
    assert controller.measurementController.measurementItems
    assert not warnings, warnings


def test_mtf_roi_uses_workspace_measurement_style(viewport):
    view, controller, pixels, warnings = viewport
    controller.settingsController.setValue('measurement', 'lineWidth', 5)
    overlay = next(i for i in _visual_children(view.rootObject()) if i.objectName() == 'mtfOverlay')
    assert overlay.property('preferences')['measurement']['lineWidth'] == 5
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length', 'angle', 'rect', 'ellipse'])
def test_live_measurements_follow_precision_without_losing_raw_values(viewport, kind, tmp_path):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.selectInteraction('measure:' + kind)
    if kind == 'angle':
        for point in [(30, 35), (95, 35), (95, 95)]:
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(pixels, *point))
            QTest.qWait(20)
    else:
        _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    measure = controller.measurementController
    raw = measure.committed_measurements
    source = controller._modality_pixel.copy()
    selected = measure.selectedMeasurementId
    for places in [0, 1, 3, 2]:
        assert controller.settingsController.setValue('measurement', 'decimalPlaces', places)
        QTest.qWait(40)
        item = visible(view.rootObject(), 'measurementItem')
        if kind == 'angle':
            assert visible(item, 'measurementLabel').property('text') == ['90°', '90.0°', '90.00°', '90.000°'][places]
        elif kind == 'length':
            assert visible(item, 'measurementLabel').property('text') == f'{raw[0].length_mm:.{places}f} mm'
        else:
            card = visible(item, 'roiMetricCard')
            rows = card.property('rows').toVariant()
            assert rows[0]['value'] == f'{raw[0].metrics.mean:.{places}f} HU'
            assert rows[-1]['value'] == str(raw[0].metrics.pixel_count)
            assert card.property('decimalPlaces') == places
            size = visible(card, 'roiGeometry-dimensions')
            assert size.property('text') == f'{raw[0].metrics.width_mm:.{places}f} × {raw[0].metrics.height_mm:.{places}f} mm'
        assert measure.committed_measurements == raw
        assert measure.selectedMeasurementId == selected
        assert (controller._modality_pixel == source).all()
    assert view.grabWindow().save(str(tmp_path / ('precision-' + kind + '.png')))
    assert not warnings, warnings


def test_linked_annotation_color_updates_existing_arrows_without_recoloring_local_marks(viewport):
    view, controller, _, warnings = viewport
    settings = controller.settingsController
    annotations = controller.textAnnotationController
    annotations.addAnnotation(30, 30, 80, 50)
    annotations.addAnnotation(100, 100, 150, 130)
    annotations.setAnnotationColor('#ff6600')
    assert settings.setValue('measurement', 'annotationFollowsCompleted', True)
    assert settings.setValue('measurement', 'completedColor', '#66d0ff')
    assert [a['color'] for a in annotations.annotationItems] == ['#66d0ff', '#ff6600']
    assert annotations.annotationColor == '#ff6600'
    # Even if the default passes through the same color, a personal mark stays fixed.
    settings.setValue('measurement', 'completedColor', '#ff6600')
    settings.setValue('measurement', 'completedColor', '#66d0ff')
    assert annotations.annotationItems[1]['color'] == '#ff6600'
    # Picking even the remembered color means an explicit override.
    custom = settings.values['measurement']['annotationColor']
    assert settings.setValue('measurement', 'annotationColor', custom)
    assert not settings.values['measurement']['annotationFollowsCompleted']
    assert settings.setValue('measurement', 'completedColor', '#808080')
    assert annotations.annotationItems[0]['color'] == custom
    assert settings.setValue('measurement', 'annotationFollowsCompleted', True)
    assert [a['color'] for a in annotations.annotationItems] == ['#808080', '#ff6600']
    assert not warnings, warnings


@pytest.mark.parametrize('legacy_color,linked', [('#66d0ff', False), ('#ffd45c', True)])
def test_legacy_arrow_color_mode_preserves_saved_appearance(tmp_path, legacy_color, linked):
    file = tmp_path / 'colors.json'
    file.write_text(json.dumps({'measurement': {'annotationColor': legacy_color}}))
    settings = SettingsController(path=file)
    assert settings.values['measurement']['annotationFollowsCompleted'] == linked
    assert settings.values['measurement']['annotationColor'] == legacy_color
    settings.setValue('measurement', 'completedColor', '#808080')
    assert SettingsController(path=file).values['measurement'] == settings.values['measurement']


def test_workspace_annotation_colors_remember_whether_they_follow_settings(viewport):
    from qt_dicom_viewer.core.workspace_state import encode, decode
    _, controller, _, _ = viewport
    annotations = controller.textAnnotationController
    annotations.addAnnotation(30, 30, 80, 50)
    controller.settingsController.setValue('measurement', 'annotationFollowsCompleted', True)
    linked = encode(annotations._annotations[annotations.selectedAnnotationId])
    explicit = deepcopy(linked)
    explicit['fields']['follows_default_color'] = False
    legacy = deepcopy(linked)
    del legacy['fields']['follows_default_color']
    controller.settingsController.setValue('measurement', 'completedColor', '#22c55e')
    for record, expected in ((linked, '#22c55e'), (explicit, linked['fields']['color']),
                             (legacy, linked['fields']['color'])):
        restored = decode(record)
        annotations._annotations = {restored.annotation_id: restored}
        annotations.selectAnnotation(restored.annotation_id)
        assert annotations.annotationColor == annotations.selected_copy()['color'] == expected
