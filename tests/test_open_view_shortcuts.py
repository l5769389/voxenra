"""Series view keys must open the intended series and respect foreground input."""
import os
import pytest
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene, right_click
from test_tag_qml import click, find


@pytest.fixture
def scene(sidebar_scene, monkeypatch):
    # Offscreen cannot embed the native VTK child; real data loading still runs.
    from qt_dicom_viewer.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    monkeypatch.setattr(VolumeViewportController, 'ensureNativeView', lambda self: None)
    monkeypatch.setattr(VolumeViewportController, 'setNativeVisible', lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    window.requestActivate()
    wait_until(window.isActive)
    app.panelController.selectSeries(records[1].series_instance_uid)
    yield window, app, records, warnings
    assert not warnings, warnings


@pytest.mark.parametrize('kind,key', [('2d', Qt.Key_D), ('mpr', Qt.Key_X),
                                     ('3d', Qt.Key_T), ('cpr', Qt.Key_Y),
                                     ('montage', Qt.Key_O), ('tag', Qt.Key_I)])
def test_selected_series_key_opens_loaded_tab_without_existing_view(scene, kind, key):
    window, app, records, _ = scene
    ws = app.workspaceController
    assert not ws.tabs
    QTest.keyClick(window, key)
    wait_until(lambda: ws.activeTab is not None)
    assert ws.activeTabType == kind
    assert ws.activeTab.tab_config.series_metas[0].series_uid == records[1].series_instance_uid
    if kind == 'tag':
        wait_until(lambda: not ws.activeTab.tagController.loading)
    else:
        wait_until(lambda: ws.activeLoadState.status == 'ready')
    assert find(window, 'workspaceTab-' + ws.activeTab.tab_config.tab_id).isVisible()
    assert not window.grabWindow().isNull()
    # Holding a key must not create many tabs.
    before = len(ws.tabs)
    QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, '', True, 1))
    assert len(ws.tabs) == before


def test_selection_text_popup_and_unsupported_view_guards(scene):
    window, app, records, _ = scene
    panel, ws = app.panelController, app.workspaceController
    panel.selectSeriesWithModifiers(records[1].series_instance_uid, True)
    QTest.keyClick(window, Qt.Key_D)
    assert not ws.tabs
    panel.selectSeries(records[1].series_instance_uid)
    QTest.keyClick(window, Qt.Key_U)  # This CT has no temporal phases.
    assert not ws.tabs
    search = find(window, 'sidebarPatientSearch')
    click(window, search)
    QTest.keyClick(window, Qt.Key_D)
    assert search.property('text').lower() == 'd' and not ws.tabs
    search.setProperty('text', '')
    find(window, 'series-' + records[1].series_instance_uid).forceActiveFocus()
    app.feedbackController.show()
    wait_until(lambda: window.property('shortcutPopupOpen'))
    QTest.keyClick(window, Qt.Key_D)
    assert not ws.tabs
    QTest.keyClick(window, Qt.Key_Escape)
    wait_until(lambda: not window.property('shortcutPopupOpen'))
    QTest.keyClick(window, Qt.Key_D)
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')


@pytest.mark.parametrize('native', [False, True])
def test_context_key_uses_right_clicked_series_and_shows_binding(scene, native, tmp_path):
    window, app, records, _ = scene
    menu = window.findChild(QObject, 'seriesContextMenu')
    menu.setProperty('popupType', 1 if native else 0)
    right_click(window, find(window, 'series-' + records[0].series_instance_uid))
    wait_until(lambda: menu.property('opened'))
    item = menu.findChild(QObject, 'seriesContextAction-2d')
    assert item.property('shortcutHint') == 'D'
    assert app.panelController.activeSeriesUid == records[1].series_instance_uid
    assert window.property('shortcutPopupOpen')
    surface = item.window()
    assert surface.grabWindow().save(str(tmp_path / f'context-keys-{native}.png'))
    QTest.keyClick(surface, Qt.Key_D)
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    assert ws.activeTabType == '2d' and len(ws.tabs) == 1
    assert ws.activeTab.tab_config.series_metas[0].series_uid == records[0].series_instance_uid
    assert not menu.property('visible')


def test_remapping_updates_hints_and_active_menu_owns_colliding_key(scene):
    window, app, records, _ = scene
    shortcuts = app.shortcutController
    assert shortcuts.assign('open-view-mpr', 'L')
    assert shortcuts.assign('open-view-2d', 'B')
    assert not shortcuts.assign('open-view-3d', 'P')  # General pan owns P.
    button = find(window, 'openView-2d').parentItem()
    assert button.property('shortcutHint') == 'B'
    QTest.keyClick(window, Qt.Key_D)
    assert not app.workspaceController.tabs
    QTest.keyClick(window, Qt.Key_B)
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    click(window, find(window, 'primaryTool-measure'))
    QTest.keyClick(window, Qt.Key_L)
    assert len(ws.tabs) == 1 and ws.activeViewport.activeInteraction == 'measure:length'
    assert find(window, 'openView-mpr').parentItem().property('shortcutHint') == ''
    QTest.keyClick(window, Qt.Key_P)
    QTest.keyClick(window, Qt.Key_L)
    wait_until(lambda: ws.activeTabType == 'mpr' and ws.activeLoadState.status == 'ready')
    assert len(ws.tabs) == 2


def test_four_d_key_keeps_temporal_series_and_loads_phase(scene, tmp_path):
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, _, _ = scene
    source = tmp_path / 'temporal'
    source.mkdir()
    records = _cross_series_four_d(source, phase_count=2)
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(source, 6, 6, 0, records))
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    window.requestActivate()
    wait_until(window.isActive)
    app.panelController.selectSeries(records[0].series_instance_uid)
    assert app.panelController.canOpenSeriesView(records[0].series_instance_uid, '4d')
    assert window.property('standardShortcutsAllowed'), window.property('shortcutPopupOpen')
    assert not window.property('editingText')
    QTest.keyClick(window, Qt.Key_U)
    wait_until(lambda: ws.activeTabType == '4d' and ws.activeLoadState.status == 'ready', timeout=15000)
    assert ws.activeTabType == '4d'
    assert ws.activeTab.tab_config.series_metas[0].series_uid == records[0].series_instance_uid
    assert ws.activeTab.currentPhaseIndex == 0


def test_compact_sidebar_and_remapped_context_key(scene):
    window, app, records, _ = scene
    click(window, find(window, 'sidebarToggle'))
    assert app.shortcutController.assign('open-view-2d', 'B')
    right_click(window, find(window, 'compactSeries-' + records[0].series_instance_uid))
    menu = window.findChild(QObject, 'seriesContextMenu')
    wait_until(lambda: menu.property('opened'))
    item = menu.findChild(QObject, 'seriesContextAction-2d')
    assert item.property('shortcutHint') == 'B'
    QTest.keyClick(item.window(), Qt.Key_D)
    assert not app.workspaceController.tabs and menu.property('visible')
    QTest.keyClick(item.window(), Qt.Key_B)
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    assert ws.activeTab.tab_config.series_metas[0].series_uid == records[0].series_instance_uid


def test_old_custom_binding_survives_new_view_defaults(qt_app, tmp_path):
    import json
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'shortcuts': {'bindings': {'pan': 'D', 'measure:angle': 'X'}}}))
    values = SettingsController(path=path).section('shortcuts')['bindings']
    assert values['pan'] == 'D' and values['open-view-2d'] == ''
    assert values['measure:angle'] == 'X' and values['open-view-mpr'] == 'X'


def test_view_keys_do_not_interrupt_pointer_drag(scene):
    from test_input_settings_qml import visible_viewport
    from PySide6.QtCore import QPointF
    window, app, _, _ = scene
    QTest.keyClick(window, Qt.Key_D)
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    viewport = visible_viewport(window)
    point = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.RightButton, Qt.NoModifier, point)
    try:
        QTest.keyClick(window, Qt.Key_X)
        assert len(ws.tabs) == 1 and ws.activeTabType == '2d'
    finally:
        QTest.mouseRelease(window, Qt.RightButton, Qt.NoModifier, point)


def test_space_remap_preserves_focused_series_selection(scene):
    window, app, records, _ = scene
    assert app.shortcutController.assign('play', '')
    assert app.shortcutController.assign('open-view-2d', 'Space')
    row = find(window, 'series-' + records[0].series_instance_uid)
    row.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    assert records[0].series_instance_uid in app.panelController.selectedSeriesUids
    assert not app.workspaceController.tabs


def test_view_labels_show_bindings_and_settings_can_clear_them(scene, tmp_path):
    window, app, _, _ = scene
    app.settingsController.setValue('appearance', 'sidebarLabels', True)
    QTest.qWait(30)
    for kind, key in [('2d', 'D'), ('mpr', 'X')]:
        button = find(window, 'openView-' + kind)
        caption = button.findChild(QObject, 'toolbarLabel')
        assert caption.isVisible() and caption.property('text').endswith('(' + key + ')')
    assert window.grabWindow().save(str(tmp_path / 'view-labels.png'))
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    QTest.qWait(60)
    assert find(window, 'shortcutRecord-open-view-2d').property('text') == 'D'
    assert app.shortcutController.assign('open-view-2d', '')
    assert not find(window, 'openView-2d').parentItem().property('shortcutHint')
    count = len(app.workspaceController.tabs)
    QTest.keyClick(window, Qt.Key_D)
    assert len(app.workspaceController.tabs) == count


@pytest.mark.skipif(os.environ.get('VOXENRA_NATIVE_QA') != '1', reason='Requires a native VTK desktop window')
def test_native_volume_focus_can_open_selected_series(sidebar_scene):
    from PySide6.QtCore import QPoint
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '3D keys', '3d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    volume = ws.activeViewport
    wait_until(lambda: volume._host is not None and volume._host.surface_ready())
    app.panelController.selectSeries(records[1].series_instance_uid)
    window.requestActivate()
    canvas = volume._host.vtk_widget
    QTest.mouseClick(canvas.windowHandle(), Qt.LeftButton, Qt.NoModifier, QPoint(60, 60))
    QTest.keyClick(QGuiApplication.focusWindow(), Qt.Key_D)
    wait_until(lambda: ws.activeTabType == '2d' and ws.activeLoadState.status == 'ready')
    assert len(ws.tabs) == 2
    assert ws.activeTab.tab_config.series_metas[0].series_uid == records[1].series_instance_uid
    assert not warnings, warnings
