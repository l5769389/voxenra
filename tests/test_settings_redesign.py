"""Exercise the redesigned settings through real QML input and rendered pixels."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QInputMethodEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click, type_text, descendants
from test_ui_polish import inside_width


def find_any(window, name):
    """Collapsed groups keep their controls mounted but invisible; find() only sees visible items."""
    def target():
        return next((item for item in descendants(window.contentItem())
                     if item.objectName() == name), None)
    wait_until(lambda: target() is not None)
    return target()


def open_page(scene, category, width=1400):
    window, app, warnings = scene
    window.resize(width, 900)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory(category)
    # The asynchronous page may be visible before its nested layouts polish.
    find(window, 'settingsPage')
    assert not window.grabWindow().isNull()
    return window, app, warnings


def reveal_setting(window, item):
    """Scroll the real settings form to a control before sending mouse input."""
    scroll = find(window, 'displaySettingsScroll').property('contentItem')
    point = item.mapToItem(scroll, QPointF(0, 0))
    current = scroll.property('contentY')
    maximum = max(0, scroll.property('contentHeight') - scroll.height())
    scroll.setProperty('contentY', max(0, min(maximum, current + point.y() - scroll.height() / 2)))
    QTest.qWait(40)


def test_corner_editor_switch_reorder_remove_add_and_preview(scene):
    window, app, warnings = open_page(scene, 'corners')
    settings = app.settingsController
    original = settings.values['corners']['topLeft'][:]
    click(window, find(window, 'cornerDown-topLeft-0'))
    assert settings.values['corners']['topLeft'] == [original[1], original[0], *original[2:]]
    click(window, find(window, 'cornerRemove-topLeft-0'))
    assert settings.values['corners']['topLeft'] == [original[0], *original[2:]]
    click(window, find(window, 'cornerSelect-topRight'))
    before = settings.values['corners']['topRight'][:]
    assert not find(window, 'cornerUp-topRight-0').isEnabled()
    choice = find(window, 'cornerChoice-topRight')
    chosen = choice.property('currentValue')
    assert chosen not in before
    click(window, find(window, 'cornerAdd-topRight'))
    assert settings.values['corners']['topRight'] == [*before, chosen]
    assert find(window, 'cornerChoice-topRight').property('currentValue') not in [*before, chosen]
    click(window, find(window, 'cornerPreview-bottomRight'))
    assert find(window, 'cornerSelect-bottomRight').property('checked')
    assert find(window, 'cornerRemove-bottomRight-0').isEnabled()
    assert not warnings, warnings


@pytest.mark.parametrize('width', [1000, 1400])
def test_color_popup_click_escape_and_persistence(scene, width):
    window, app, warnings = open_page(scene, 'measurement', width)
    picker = find(window, 'colorPicker-measurement-editingColor')
    click(window, picker)
    colors = [i for i in descendants(window.contentItem()) if i.isVisible() and i.objectName().startswith('colorChoice-measurement-editingColor-')]
    assert len(colors) == 8
    for color in colors:
        inside_width(color, window.contentItem())
    click(window, find(window, 'colorChoice-measurement-editingColor-22c55e'))
    assert app.settingsController.values['measurement']['editingColor'] == '#22c55e'
    assert not any(i.isVisible() for i in colors)
    assert find(window, 'setting-measurement-editingColor').property('text') == '#22c55e'
    click(window, picker)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not any(i.isVisible() for i in colors)
    assert not warnings, warnings


def test_numeric_input_updates_preview_and_restores_invalid_input(scene):
    window, app, warnings = open_page(scene, 'measurement')
    field = find(window, 'settingInput-measurement-lineWidth')
    type_text(window, field, '2.75')
    QTest.keyClick(window, Qt.Key_Tab)
    assert app.settingsController.values['measurement']['lineWidth'] == 2.75
    # Invalid intermediate input must not remain displayed after losing focus.
    type_text(window, field, '9')
    QTest.keyClick(window, Qt.Key_Tab)
    assert field.property('text') == '2.75'
    assert app.settingsController.values['measurement']['lineWidth'] == 2.75
    type_text(window, field, '')
    QTest.keyClick(window, Qt.Key_Tab)
    assert field.property('text') == '2.75'
    slider = find(window, 'setting-measurement-lineWidth')
    slider.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Right)
    assert app.settingsController.values['measurement']['lineWidth'] > 2.75
    assert not warnings, warnings


@pytest.mark.parametrize('width', [1000, 1400, 2000])
def test_window_table_columns_align_and_editor_stays_compact(scene, width, tmp_path):
    window, app, warnings = open_page(scene, 'window', width)
    for suffix in ['WW', 'WL']:
        header = find(window, 'windowHeader' + suffix)
        right = header.mapToScene(QPointF(header.width(), 0)).x()
        cells = [i for i in descendants(window.contentItem()) if i.isVisible() and i.objectName().startswith('window' + suffix + '-')]
        assert len(cells) == len(app.settingsController.windowTemplates) == 13
        for cell in cells:
            assert cell.mapToScene(QPointF(cell.width(), 0)).x() == pytest.approx(right, abs=1)
    for field_name in ['windowTemplateWidth', 'windowTemplateCenter']:
        assert find(window, field_name).width() <= 100
    reveal_setting(window, find_any(window, 'windowTemplateName'))
    type_text(window, find(window, 'windowTemplateName'), 'Review preset')
    click(window, find(window, 'saveWindowTemplate'))
    identifier = app.settingsController.values['window']['custom'][0]['presetId']
    reveal_setting(window, find_any(window, 'windowEdit-' + identifier))
    click(window, find(window, 'windowEdit-' + identifier))
    reveal_setting(window, find_any(window, 'windowTemplateCenter'))
    type_text(window, find(window, 'windowTemplateCenter'), '-100')
    click(window, find(window, 'saveWindowTemplate'))
    assert app.settingsController.values['window']['custom'][0]['center'] == -100
    assert window.grabWindow().save(str(tmp_path / f'window-{width}.png'))
    reveal_setting(window, find_any(window, 'windowDelete-' + identifier))
    click(window, find(window, 'windowDelete-' + identifier))
    assert not app.settingsController.values['window']['custom']
    assert not warnings, warnings


@pytest.mark.parametrize('category', ['crosshair', 'corners', 'scale', 'measurement', 'roi'])
def test_settings_preview_remains_bounded_on_wide_screens(scene, category, tmp_path):
    window, app, warnings = open_page(scene, category, 2000)
    preview = find(window, 'settingsPreviewColumn')
    form = find(window, 'settingsParameterColumn')
    assert 240 <= preview.width() <= (380 if category == "measurement" else 280)
    assert preview.height() > 80
    assert preview.mapToScene(QPointF()).x() > form.mapToScene(QPointF()).x() + form.width()
    for item in descendants(window.contentItem()):
        if item.isVisible() and item.objectName().startswith(('setting-', 'settingInput-', 'cornerSelect-', 'colorPicker-')):
            inside_width(item, form)
    assert window.grabWindow().save(str(tmp_path / f'{category}-2000.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('size', [24, 28, 48])
def test_mpr_crosshair_and_color_mapping_are_legible_at_toolbar_sizes(qt_app, size, tmp_path):
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setColor(QColor('black'))
    view.setInitialProperties({'iconName': 'nav-view-mpr', 'iconSize': size})
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/components/AppIcon.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    try:
        QTest.qWait(80)
        frame = view.grabWindow()
        # The reference point and all four crosshair arms remain visible at toolbar size.
        middle_x, middle_y = frame.width() // 2, frame.height() // 2
        assert frame.pixelColor(middle_x, middle_y).lightness() > 50
        for x, y in [(middle_x, size // 5), (middle_x, size * 4 // 5),
                     (size // 5, middle_y), (size * 4 // 5, middle_y)]:
            assert any(frame.pixelColor(x + dx, y + dy).lightness() > 50
                       for dx in [-1, 0, 1] for dy in [-1, 0, 1])
        assert frame.save(str(tmp_path / f'mpr-{size}.png'))
        view.rootObject().setProperty('iconName', 'pseudocolor')
        QTest.qWait(80)
        frame = view.grabWindow()
        pixels = [frame.pixelColor(x, y) for x in range(frame.width()) for y in range(frame.height())]
        # Both a grayscale ramp and warm/cool colored pixels survive downscaling.
        assert sum(c.lightness() > 80 and c.saturation() < 60 for c in pixels) >= 8
        assert sum(c.red() > c.blue() + 35 for c in pixels) >= 8
        assert sum(c.blue() > c.red() + 35 for c in pixels) >= 8
        assert frame.save(str(tmp_path / f'pseudocolor-{size}.png'))
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)


@pytest.mark.parametrize('width, theme', [(1000, 'dark'), (1400, 'light')])
def test_measurement_precision_dropdown_updates_and_restores_settings(scene, width, theme, tmp_path):
    scene[1].settingsController.setValue('appearance', 'theme', theme)
    window, app, warnings = open_page(scene, 'measurement', width)
    search = find(window, 'settingsSearch')
    search.forceActiveFocus()
    event = QInputMethodEvent()
    event.setCommitString('精度')
    QGuiApplication.sendEvent(window.focusObject(), event)
    QTest.qWait(30)
    assert find(window, 'settingsCategory-measurement').isVisible()
    type_text(window, find(window, 'settingsSearch'), '')
    selector = find(window, 'setting-measurement-decimalPlaces')
    assert selector.property('currentText') == '2 位小数'
    click(window, selector)
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / ('measurement-precision-menu-' + theme + '.png')))
    QTest.keyClick(window, Qt.Key_Home)
    QTest.keyClick(window, Qt.Key_Return)
    assert app.settingsController.values['measurement']['decimalPlaces'] == 0
    assert selector.property('currentText') == '整数（0 位小数）'
    reveal_setting(window, selector)
    click(window, selector)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    assert app.settingsController.values['measurement']['decimalPlaces'] == 3
    app.settingsController.resetSection('measurement')
    assert selector.property('currentText') == '2 位小数'
    assert not warnings, warnings


def test_mtf_frequency_unit_dropdown_updates_and_restores_settings(scene, tmp_path):
    window, app, warnings = open_page(scene, 'services', 1100)
    type_text(window, find(window, 'settingsSearch'), 'MTF')
    assert find(window, 'settingsCategory-services').isVisible()
    type_text(window, find(window, 'settingsSearch'), '')
    selector = find(window, 'setting-services-mtfFrequencyUnit')
    assert selector.property('currentText') == 'lp/mm'
    reveal_setting(window, selector)
    click(window, selector)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(40)
    assert app.settingsController.values['services']['mtfFrequencyUnit'] == 'lp/cm'
    assert selector.property('currentText') == 'lp/cm'
    assert window.grabWindow().save(str(tmp_path / 'mtf-unit-setting.png'))
    print(f'MTF unit settings preview: {tmp_path / "mtf-unit-setting.png"}')
    app.settingsController.resetSection('services')
    assert selector.property('currentText') == 'lp/mm'
    assert not warnings, warnings


def test_ramp_angle_selector_updates_and_resets(scene, tmp_path):
    window, app, warnings = open_page(scene, 'services', 1100)
    selector = find(window, 'setting-services-rampThicknessAngle')
    assert '23°' in selector.property('currentText')
    reveal_setting(window, selector)
    click(window, selector)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(40)
    assert app.settingsController.values['services']['rampThicknessAngle'] == 45
    assert '45°' in selector.property('currentText')
    path = tmp_path / 'ramp-settings-github.png'
    assert window.grabWindow().save(str(path))
    print(f'Ramp settings preview: {path}')
    app.settingsController.resetSection('services')
    assert '23°' in selector.property('currentText')
    assert not warnings, warnings


def test_metric_card_settings_have_live_interactive_preview(scene, tmp_path):
    from test_measurement_qml import _mouse_drag
    from PySide6.QtCore import QPoint
    window, app, warnings = open_page(scene,'measurement',1600)
    settings=app.settingsController
    card=find(window,'measurementPreviewCard')
    shape=find(window,'measurementPreviewShape')
    type_text(window,find(window,'settingInput-measurement-fontSize'),'18')
    QTest.keyClick(window,Qt.Key_Tab)
    type_text(window,find(window,'settingInput-measurement-cardTransparency'),'60')
    QTest.keyClick(window,Qt.Key_Tab)
    assert card.property('metricFontSize')==18
    assert card.property('color').alphaF()==pytest.approx(.4,abs=.005)
    click(window,find(window,'setting-measurement-linkLabelToShape'))
    assert settings.values['measurement']['linkLabelToShape']
    sy,cy=shape.y(),card.y()
    start=shape.mapToScene(QPointF(shape.width()/2,shape.height()/2)).toPoint()
    _mouse_drag(window,start,start+QPoint(0,12))
    assert shape.y()==pytest.approx(sy+12,abs=1)
    assert card.y()==pytest.approx(cy+12,abs=1)
    click(window,find(window,'setting-measurement-linkLabelToShape'))
    sy,cy=shape.y(),card.y()
    start=card.mapToScene(QPointF(card.width()/2,card.height()/2)).toPoint()
    _mouse_drag(window,start,start+QPoint(0,10))
    assert shape.y()==sy
    assert card.y()==pytest.approx(cy+10,abs=1)
    assert window.grabWindow().save(str(tmp_path/'metric-card-settings.png'))
    assert not warnings,warnings


def test_settings_group_collapse_survives_page_reload_and_language_switch(scene, tmp_path):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    window, app, warnings = open_page(scene, 'measurement')
    settings = app.settingsController
    click(window, find(window, 'settingsGroup-measurement-cards'))
    assert settings.values['layout']['settingsCollapsedGroups'] == ['measurement-cards']
    assert not find_any(window, 'setting-measurement-linkLabelToShape').isVisible()
    loaded = SettingsController(path=tmp_path / 'display-settings.json')
    assert loaded.values['layout']['settingsCollapsedGroups'] == ['measurement-cards']
    settings.selectCategory('scale')
    find(window, 'setting-scale-enabled')
    settings.setValue('appearance', 'language', 'en-US')
    settings.selectCategory('measurement')
    group = find(window, 'settingsGroup-measurement-cards')
    assert not find_any(window, 'setting-measurement-linkLabelToShape').isVisible()
    click(window, group)
    assert find(window, 'setting-measurement-linkLabelToShape').isVisible()
    assert SettingsController(path=tmp_path / 'display-settings.json').values['layout']['settingsCollapsedGroups'] == []
    assert not warnings, warnings


@pytest.mark.parametrize('width', [1000, 1400])
def test_mtf_equivalent_setting_default_toggle_and_reset(scene, tmp_path, width):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    window, app, warnings = open_page(scene, 'services', width)
    checkbox = find(window, 'setting-services-mtfGaussianEquivalent')
    assert checkbox.property('checked')
    assert 'MTF10' in checkbox.property('text')
    reveal_setting(window, checkbox)
    help_text = find(window, 'mtfEquivalentSettingHelp')
    assert '模型估计' in help_text.property('text')
    inside_width(help_text, window.contentItem())
    assert window.grabWindow().save(str(tmp_path/f'mtf-equivalent-settings-{width}.png'))
    click(window, checkbox)
    assert not app.settingsController.section('services')['mtfGaussianEquivalent']
    loaded = SettingsController(path=app.settingsController._path)
    assert not loaded.section('services')['mtfGaussianEquivalent']
    app.settingsController.resetSection('services')
    assert checkbox.property('checked')
    assert not warnings, warnings


def test_service_settings_have_own_navigation_search_and_reset(scene):
    window, app, warnings = open_page(scene, 'measurement')
    settings = app.settingsController
    assert not any(item.objectName().startswith('setting-services-')
                   for item in descendants(window.contentItem()))
    settings.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
    settings.setValue('services', 'mtfGaussianEquivalent', False)
    settings.setValue('services', 'rampThicknessAngle', 45)
    calculations = settings.section('services')
    click(window, find(window, 'resetDisplaySettings'))
    assert settings.section('services') == calculations
    settings.setValue('measurement', 'fontSize', 18)
    type_text(window, find(window, 'settingsSearch'), 'MTF')
    assert not find_any(window, 'settingsCategory-measurement').isVisible()
    click(window, find(window, 'settingsCategory-services'))
    assert settings.activeCategory == 'services'
    assert not find(window, 'setting-services-mtfGaussianEquivalent').property('checked')
    assert find(window, 'setting-services-mtfFrequencyUnit').property('currentText') == 'lp/cm'
    assert '45°' in find(window, 'setting-services-rampThicknessAngle').property('currentText')
    click(window, find(window, 'resetDisplaySettings'))
    assert find(window, 'setting-services-mtfGaussianEquivalent').property('checked')
    assert settings.section('measurement')['fontSize'] == 18
    assert settings.section('services')['mtfFrequencyUnit'] == 'lp/mm'
    assert settings.section('services')['rampThicknessAngle'] == 23
    settings.setValue('appearance', 'language', 'en-US')
    assert find(window, 'settingsCategory-services').property('contentItem').property('text') == 'Service tools'
    assert 'Gaussian equivalent' in find(window, 'setting-services-mtfGaussianEquivalent').property('text')
    assert not warnings, warnings
