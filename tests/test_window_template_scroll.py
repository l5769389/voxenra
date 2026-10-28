"""Window presets scroll without moving their inputs or applying a favorite."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QMetaObject, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, type_text, descendants
from test_display_settings_qml import select_category


def wheel(window, item, delta=-120, pixel=False):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    event = QWheelEvent(point, QPointF(window.mapToGlobal(point.toPoint())),
                        QPoint(0, delta) if pixel else QPoint(),
                        QPoint() if pixel else QPoint(0, delta),
                        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QCoreApplication.sendEvent(window, event)
    QTest.qWait(25)


def open_window_panel(scene):
    window, app, records, warnings = scene
    window.resize(1280, 720)
    app.panelController.selectSeries(records[0].series_instance_uid)
    app.panelController.openSeriesView(records[0].series_instance_uid, '2d')
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and bool(app.workspaceController.activeViewport.imageSource))
    app.workspaceController.activeViewport._tool_controller.activateTool('window')
    QTest.qWait(100)
    return window, app, app.workspaceController.activeViewport, warnings


def test_window_controls_survive_resize_while_first_tab_is_constructed(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    # Window limits settle while the first image page and its tool panel load.
    # A transient compact layout must not tear down a creating window editor.
    window.resize(1000, 600)
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'Resize during open', '2d')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    QTest.qWait(100)
    assert not find(window, 'rightPanel').property('collapsed')
    assert workspace.activeViewport._tool_controller.activePanel == 'window'
    assert find(window, 'windowWidthInput').isVisible()
    assert not warnings, warnings


@pytest.mark.parametrize('pixel', [False, True])
def test_window_list_wheel_keeps_inputs_and_outer_panel_fixed(sidebar_scene, tmp_path, pixel):
    window, app, view, warnings = open_window_panel(sidebar_scene)
    outer = find(window, 'toolDetailFlickable')
    width_input = find(window, 'windowWidthInput')
    fixed_position = width_input.mapToScene(QPointF())
    # Start on a visible template; old behavior scrolls the whole panel here.
    first = find(window, 'windowPreset-ct-brain')
    listing = first.parentItem().parentItem()
    wheel(window, first, -80 if pixel else -120, pixel)
    assert width_input.mapToScene(QPointF()) == fixed_position
    assert outer.property('contentY') == 0
    assert listing.property('contentY') > 0
    assert listing.height() < listing.property('contentHeight')
    assert outer.property('contentHeight') <= outer.height()
    for _ in range(25):
        wheel(window, listing, -200 if pixel else -1200, pixel)
    assert listing.property('atYEnd')
    bottom = listing.property('contentY')
    wheel(window, listing, -200 if pixel else -1200, pixel)
    assert listing.property('contentY') == bottom
    assert outer.property('contentY') == 0
    assert width_input.mapToScene(QPointF()) == fixed_position
    last = find(window, 'windowPreset-ct-spine-bone')
    click(window, last)
    wait_until(lambda: view.current_window.width == 1800 and view.current_window.center == 400)
    assert last.property('checked')
    type_text(window, width_input, '1234')
    type_text(window, find(window, 'windowCenterInput'), '-456')
    click(window, find(window, 'applyWindowValues'))
    wait_until(lambda: view.current_window.width == 1234 and view.current_window.center == -456)
    for _ in range(25):
        wheel(window, listing, 200 if pixel else 1200, pixel)
    assert listing.property('atYBeginning')
    wheel(window, listing, 200 if pixel else 1200, pixel)
    assert outer.property('contentY') == 0
    ww = find(window, 'windowPresetWW-ct-brain')
    wl = find(window, 'windowPresetWL-ct-brain')
    assert ww.mapToScene(QPointF()).x() < wl.mapToScene(QPointF()).x()
    assert float(ww.property('text')) == 80 and float(wl.property('text')) == 40
    destination = Path('build/reading-controls'); destination.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(destination / ('window-presets-pixel.png' if pixel else 'window-presets-wheel.png')))
    assert not warnings, warnings


def test_favorites_persist_without_changing_preset_file_order_or_numbers(qt_app, tmp_path):
    path = tmp_path / 'settings.json'
    settings = SettingsController(path=path)
    original = [p['presetId'] for p in settings.window_presets]
    preset_bytes = Path(settings.windowPresetsPath).read_bytes()
    assert settings.setWindowTemplateFavorite('ct-spine-bone', True)
    assert settings.setWindowTemplateFavorite('ct-lung', True)
    assert [p['presetId'] for p in settings.window_presets[:2]] == ['ct-lung', 'ct-spine-bone']
    assert Path(settings.windowPresetsPath).read_bytes() == preset_bytes
    assert settings.setValue('appearance', 'theme', 'light')
    restarted = SettingsController(path=path)
    assert restarted.values['window']['favorites'] == ['ct-spine-bone', 'ct-lung']
    assert restarted.window_presets == settings.window_presets
    assert restarted.enableWindowTemplate('ct-lung', False)
    assert restarted.window_presets[0]['presetId'] == 'ct-spine-bone'
    assert not any(p['presetId'] == 'ct-lung' for p in restarted.window_presets)
    assert restarted.enableWindowTemplate('ct-lung', True)
    assert restarted.setWindowTemplateFavorite('ct-spine-bone', False)
    assert restarted.setWindowTemplateFavorite('ct-lung', False)
    assert [p['presetId'] for p in restarted.window_presets] == original
    assert restarted.saveWindowTemplate('', 'Test Favorite', 1234, -456)
    custom = restarted.window_presets[-1]['presetId']
    assert restarted.setWindowTemplateFavorite(custom, True)
    assert restarted.deleteWindowTemplate(custom)
    assert restarted.values['window']['favorites'] == []
    assert SettingsController(path=path).values['window']['favorites'] == []
    assert custom not in json.loads(path.read_text()).get('window', {}).get('favorites', [])


def test_invalid_favorites_cannot_corrupt_settings_or_template_values(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    before = settings.windowTemplates
    for bad in (None, 'ct-brain', [None], ['../escape'], ['x'] * 101):
        assert not settings.setValue('window', 'favorites', bad)
    assert not settings.setWindowTemplateFavorite('missing', True)
    assert settings.windowTemplates == before
    assert settings.values['window']['favorites'] == []


def test_star_toggle_is_shared_with_settings_and_does_not_apply_window(sidebar_scene):
    window, app, view, warnings = open_window_panel(sidebar_scene)
    view.applyWindowPreset(-123, 987)
    QTest.qWait(50)
    click(window, find(window, 'windowFavorite-ct-lung'))
    assert app.settingsController.values['window']['favorites'] == ['ct-lung']
    assert (view.current_window.width, view.current_window.center) == (987, -123)
    assert find(window, 'windowFavorite-ct-lung').property('checked')
    assert find(window, 'windowPreset-ct-lung').mapToScene(QPointF()).y() < find(window, 'windowPreset-ct-brain').mapToScene(QPointF()).y()
    app.workspaceController.openSettings()
    QTest.qWait(70)
    select_category(window, 'window')
    QTest.qWait(70)
    star = find(window, 'settingWindowFavorite-ct-lung')
    assert star.property('checked')
    click(window, star)
    assert app.settingsController.values['window']['favorites'] == []
    assert (view.current_window.width, view.current_window.center) == (987, -123)
    assert not warnings, warnings


def test_failed_favorite_save_keeps_star_and_window_unchanged(sidebar_scene, tmp_path):
    window, app, view, warnings = open_window_panel(sidebar_scene)
    before = (view.current_window.width, view.current_window.center)
    # QSaveFile cannot replace a directory; exercise the real write failure.
    path = tmp_path / 'unwritable-settings.json'
    path.mkdir()
    app.settingsController._path = path
    star = find(window, 'windowFavorite-ct-lung')
    click(window, star)
    assert app.settingsController.values['window']['favorites'] == []
    assert not star.property('checked')
    assert find(window, 'windowInputError').property('text')
    assert (view.current_window.width, view.current_window.center) == before
    assert not warnings, warnings


def test_short_compact_window_popup_keeps_actions_visible(sidebar_scene, monkeypatch):
    from test_mpr_volume_tools_qml import item_window
    from test_window_sizing import fit_desktop
    window, app, view, warnings = open_window_panel(sidebar_scene)
    fit_desktop(window, app, monkeypatch, (800, 600))
    assert find(window, 'rightPanel').property('collapsed')
    popup = window.findChild(QObject, 'compactVolumePanel')
    popup.setProperty('panelTool', 'window')
    QMetaObject.invokeMethod(popup, 'open')
    wait_until(lambda: popup.property('visible'))
    # Resolve controls inside the actual native popup window, not the hidden
    # expanded panel, which has objects with the same local names.
    content = popup.property('contentItem')
    def visible_list():
        return next((item for item in descendants(content)
                     if item.objectName() == 'windowPresetList' and item.isVisible() and item.height() > 0), None)
    wait_until(lambda: visible_list() is not None)
    listing = visible_list()
    popup_window = item_window(listing)
    width_input = find(popup_window, 'windowWidthInput')
    fixed_position = width_input.mapToScene(QPointF())
    for name in ('windowWidthInput', 'windowCenterInput', 'applyWindowValues', 'beginSaveWindowTemplate'):
        item = find(popup_window, name)
        pos = item.mapToScene(QPointF())
        assert 0 <= pos.y() < pos.y() + item.height() <= popup_window.height()
    for _ in range(15):
        wheel(popup_window, listing, -1200)
    assert listing.property('atYEnd')
    assert width_input.mapToScene(QPointF()) == fixed_position
    click(popup_window, find(popup_window, 'windowPreset-ct-spine-bone'))
    wait_until(lambda: view.current_window.width == 1800 and view.current_window.center == 400)
    destination = Path('build/reading-controls'); destination.mkdir(parents=True, exist_ok=True)
    assert popup_window.grabWindow().save(str(destination / 'window-presets-compact.png'))
    assert not warnings, warnings
