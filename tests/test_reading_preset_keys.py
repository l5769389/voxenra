"""Exercise list position keys through the real reading window."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest

from qt_pointer import move_pointer
from qt_dicom_viewer.settings.shortcuts import validate_bindings
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene
from test_series_sidebar import sidebar_scene
from test_pet_fusion import paired_series
from test_tag_qml import click, descendants, find, settled_point


def test_window_presets_follow_visible_order_and_leave_number_fields_alone(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    settings = app.settingsController
    QTest.keyClick(window, Qt.Key_W)
    app.settingsController.setValue('layout', 'rightPanelWidth', 240)
    name = find(window, 'windowPresetName-ct-brain')
    wait_until(lambda: not name.property('truncated'))
    for index in (0, 8):
        preset = view.windowPresets[index]
        QTest.keyClick(window, Qt.Key_1 + index)
        assert (view.windowWidth, view.windowCenter) == (preset['width'], preset['center'])
        row = find(window, 'windowPreset-' + preset['presetId'])
        assert row.property('checked') and row.property('hint').endswith(str(index + 1))
    settings.setWindowTemplateFavorite(preset['presetId'], True)
    assert view.windowPresets[0]['presetId'] == preset['presetId']
    QTest.keyClick(window, Qt.Key_2)
    QTest.keyClick(window, Qt.Key_1)
    assert (view.windowWidth, view.windowCenter) == (preset['width'], preset['center'])
    assert settings.enableWindowTemplate(preset['presetId'], False)
    QTest.keyClick(window, Qt.Key_1)
    expected = view.windowPresets[0]
    assert expected['presetId'] != preset['presetId']
    assert (view.windowWidth, view.windowCenter) == (expected['width'], expected['center'])
    field = find(window, 'windowWidthInput')
    click(window, field)
    field.selectAll()
    QTest.keyClick(window, Qt.Key_3)
    assert field.property('text') == '3'
    assert view.windowWidth == expected['width']
    assert not sidebar_scene[3], sidebar_scene[3]


def test_scroll_ends_zoom_factors_and_list_key_remap(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    v = tab.activeViewport
    QTest.keyClick(window, Qt.Key_S)
    for key, index, name in [(Qt.Key_L, v.sliceCount - 1, 'last'), (Qt.Key_H, 0, 'first')]:
        QTest.keyClick(window, key)
        assert v.sliceIndex == index and not find(window, 'scrollShortcut-' + name).isEnabled()
    QTest.keyClick(window, Qt.Key_K)
    assert v.sliceIndex == 1
    QTest.keyClick(window, Qt.Key_J)
    assert v.sliceIndex == 0
    QTest.keyClick(window, Qt.Key_Z)
    for factor in range(1, 11):
        QTest.keyClick(window, Qt.Key_0 + factor % 10)
        assert v.zoom == factor and find(window, 'zoomSlider').property('value') == factor
    assert find(window, 'zoomToolPanel').property('defaultKeys')
    assert app.shortcutController.assign('zoom-3', 'F7')
    assert '3× (F7)' in find(window, 'zoomHeading').property('explanation')
    QTest.keyClick(window, Qt.Key_F7)
    assert v.zoom == 3
    QTest.keyClick(window, Qt.Key_2, Qt.KeypadModifier)
    assert v.zoom == 2
    QTest.keyClick(window, Qt.Key_L)
    assert v.sliceIndex == 0
    QTest.keyClick(window, Qt.Key_M)
    QTest.keyClick(window, Qt.Key_A)
    QTest.keyClick(window, Qt.Key_L)
    assert v.activeInteraction == 'measure:length' and v.sliceIndex == 0
    assert app.shortcutController.assign('list-2', 'F8')
    QTest.keyClick(window, Qt.Key_W)
    QTest.keyClick(window, Qt.Key_1)
    first = v.windowWidth, v.windowCenter
    QTest.keyClick(window, Qt.Key_2)
    assert (v.windowWidth, v.windowCenter) == first
    QTest.keyClick(window, Qt.Key_F8)
    target = v.windowPresets[1]
    assert (v.windowWidth, v.windowCenter) == (target['width'], target['center'])
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('compact', [False, True])
def test_palette_keys_favorites_and_popup_lifetime(sidebar_scene, compact):
    window, app, tab = reading_scene(sidebar_scene)
    if compact:
        click(window, find(window, 'toggleRightPanel'))
    def open_palette():
        QTest.keyClick(window, Qt.Key_C)
        panel = find(window, 'pseudoColorPanel')
        wait_until(lambda: panel.width() > 50)
        return panel
    panel = open_palette()
    assert window.property('activeReadingMenu') == 'pseudocolor'
    palette = panel.property('options').toVariant()[2]['colorMap']
    prefix = 'compactAction-' if compact else 'colorMap-'
    star = find(window, prefix + 'favorite-' + palette)
    old = tab.activeViewport.activeColorMap
    click(window, star)
    wait_until(lambda: app.settingsController.section('paletteList')['favorites'] == [palette])
    assert tab.activeViewport.activeColorMap == old
    assert SettingsController(path=app.settingsController._path).section('paletteList')['favorites'] == [palette]
    assert panel.property('options').toVariant()[0]['colorMap'] == palette
    QTest.keyClick(window, Qt.Key_1)
    wait_until(lambda: tab.activeViewport.activeColorMap == palette)
    if compact:
        wait_until(lambda: not window.property('activeReadingMenu'))
        QTest.keyClick(window, Qt.Key_2)
        assert tab.activeViewport.activeColorMap == palette
        panel = open_palette()
    else:
        assert find(window, prefix + palette).property('checked')
    ninth = panel.property('options').toVariant()[8]['colorMap']
    QTest.keyClick(window, Qt.Key_9)
    wait_until(lambda: tab.activeViewport.activeColorMap == ninth)
    QTest.keyClick(window, Qt.Key_P)
    QTest.keyClick(window, Qt.Key_1)
    assert tab.activeViewport.activeColorMap == ninth
    assert not sidebar_scene[3], sidebar_scene[3]


def test_new_palette_key_keeps_existing_user_bindings(qt_app):
    migrated = validate_bindings({'pan': 'C', 'cpr-new': '2'})
    assert migrated['pan'] == 'C' and migrated['pseudocolor'] == ''
    assert migrated['cpr-new'] == '2' and migrated['list-2'] == '2'


def test_hover_only_opens_when_it_adds_information(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    app.settingsController.setValue('layout', 'rightPanelWidth', 420)
    QTest.keyClick(window, Qt.Key_M)
    angle = find(window, 'measureEntry-angle')
    label = next(i for i in descendants(angle) if i.objectName() == 'toolActionLabel')
    assert label.property('text') == angle.property('tooltipText')
    move_pointer(window, settled_point(angle))
    wait_until(lambda: angle.property('hovered'))
    tip = next(t for t in angle.children() if t.property('delay') == 400)
    QTest.qWait(520)
    assert not tip.property('visible')
    scroll = find(window, 'primaryTool-scroll')
    owner = scroll.parentItem()
    move_pointer(window, settled_point(scroll))
    wait_until(lambda: owner.property('hovered') and window.isActive())
    # A native tooltip opens on a delayed Qt event. Keep the event loop active.
    if not owner.property('tooltipVisible'):
        spy = QSignalSpy(owner.tooltipVisibleChanged)
        assert spy.wait(3000)
    assert owner.property('tooltipVisible')
    assert owner.property('explanation') and owner.property('explanation') in owner.property('tooltipText')
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('compact', [False, True])
def test_fusion_preset_and_palette_keys_respect_selected_target(sidebar_scene, paired_series, tmp_path, compact):
    from PySide6.QtCore import QObject
    from test_cpr_footer import item_window
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, _, warnings = sidebar_scene
    _, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    app.workspaceController.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.ready)
    window.requestActivate()
    click(window, find(window, 'primaryTool-ct-window'))
    QTest.keyClick(window, Qt.Key_9)
    preset = [row for row in app.settingsController.windowTemplates if row['enabled']][8]
    assert (tab.ctWidth, tab.ctCenter) == (preset['width'], preset['center'])
    if compact:
        click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_C)
    surface = window
    if compact:
        popup = window.findChild(QObject, 'compactVolumePanel')
        wait_until(lambda: popup.property('opened'))
        surface = item_window(popup.property('contentItem'))
    before = tab.petColorMap
    click(surface, find(surface, 'paletteTarget-fusion'))
    panel = find(surface, 'pseudoColorPanel')
    target = panel.property('options').toVariant()[2]['colorMap']
    QTest.keyClick(surface, Qt.Key_3)
    assert tab.fusionColorMap == target and tab.petColorMap == before
    assert not warnings, warnings
