"""User toolbar drafts persist stable identities and never discard hidden tools."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QObject

from qt_dicom_viewer.model import TabType, SeriesDisplayMeta
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from test_dicom_tags import qt_app
from test_series_sidebar import sidebar_scene


def attached_tools(settings, **kwargs):
    parent = QObject()
    parent._settings_controller = settings
    controller = ToolController(parent, **kwargs)
    controller._test_owner = parent
    return controller


def test_saved_toolbar_order_survives_restart_and_capability_filtering(qt_app, tmp_path):
    path = tmp_path / 'settings.json'
    settings = SettingsController(path=path)
    preference = {'2d:ct': {'common': ['service', 'zoom', 'window'], 'more': ['export', 'pan']}}
    assert settings.setValue('toolbar', 'rightProfiles', preference)
    tools = attached_tools(settings, tab_type=TabType.TWO_D, modality='CT')
    assert tools.toolbarGroups['common'] == ['service', 'zoom', 'window']
    tools.set_series_capabilities(SeriesDisplayMeta(patient_name='', patient_id='', study_description='',
        series_description='', series_uid='reduced', modality='CT', supports_ct_analysis=False))
    assert tools.toolbarGroups['common'] == ['zoom', 'window']
    assert settings.section('toolbar')['rightProfiles'] == preference
    settings.setValue('appearance', 'language', 'en-US')
    restored = SettingsController(path=path)
    live = attached_tools(restored, tab_type=TabType.TWO_D, modality='CT')
    assert [t['toolType'] for t in live.orderedToolbarTools][:5] == ['service', 'zoom', 'window', 'export', 'pan']


@pytest.mark.parametrize('value', [
    {'2d:ct': {'common': ['window'] * 2, 'more': []}},
    {'2d:ct': {'common': ['window'], 'more': ['window']}},
    {'2d:ct': {'common': ['a','b','c','d','e','f','g','h'], 'more': []}},
    {'2d:ct': {'common': 'window', 'more': []}},
    {'../bad': {'common': [], 'more': []}},
])
def test_invalid_toolbar_preferences_do_not_replace_saved_values(qt_app, value):
    settings = SettingsController(path=False)
    assert settings.setValue('toolbar', 'rightProfiles', {'2d:ct': {'common':['zoom'], 'more':[]}})
    before = settings.values
    assert not settings.setValue('toolbar', 'rightProfiles', value)
    assert settings.values == before


def test_editor_cancel_limit_reset_and_atomic_save(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    assert hasattr(settings, 'createToolbarEditor'), 'Settings must provide the toolbar draft editor'
    editor = settings.createToolbarEditor(settings)
    editor.beginEdit()
    before = deepcopy(settings.values)
    assert [t['toolType'] for t in editor.commonTools] == ['window','scroll','pan','zoom','measure','mpr-layout','play']
    assert not editor.moveToGroup('export', 'common')
    assert editor.moveToGroup('play', 'more')
    assert editor.moveToGroup('export', 'common')
    assert editor.moveTool('common', 6, 0)
    assert editor.moveLeftView(2, 0)
    assert settings.values == before
    editor.cancel()
    assert editor.leftViews[0]['toolType'] == '2d'
    assert editor.commonTools[0]['toolType'] == 'window'
    assert editor.moveTool('common', 3, 0)
    assert editor.moveLeftView(2, 0)
    assert editor.save()
    assert not editor.dirty
    restored = SettingsController(path=settings._path)
    assert restored.navigationViewOrder[:3] == ['3d', '2d', 'mpr']
    assert restored.section('toolbar')['rightProfiles']['2d:ct']['common'][0] == 'zoom'
    editor.restoreCurrentDefault()
    assert editor.commonTools[0]['toolType'] == 'window'
    assert settings.section('toolbar')['rightProfiles']['2d:ct']['common'][0] == 'zoom'
    editor.cancel()
    assert editor.commonTools[0]['toolType'] == 'zoom'


def test_new_tool_is_appended_to_more_without_losing_unknown_preference(qt_app):
    settings = SettingsController(path=False)
    saved = {'2d:ct': {'common': ['zoom'], 'more': ['future-tool', 'export']}}
    assert settings.setValue('toolbar', 'rightProfiles', saved)
    tools = attached_tools(settings, tab_type=TabType.TWO_D, modality='CT')
    assert tools.toolbarGroups['more'][0] == 'export'
    assert 'window' in tools.toolbarGroups['more']
    assert 'future-tool' not in tools.toolbarGroups['more']
    assert settings.section('toolbar')['rightProfiles'] == saved


def test_left_fixed_actions_rejected_and_missing_views_appended(qt_app):
    settings = SettingsController(path=False)
    assert settings.setValue('toolbar', 'leftViews', ['3d', 'mpr'])
    assert settings.navigationViewOrder == ['3d','mpr','2d','montage','4d','tag','fusion']
    assert not settings.setValue('toolbar', 'leftViews', ['file','pacs','3d'])


def test_qml_toolbar_draft_arrows_drag_save_cancel(qt_app, tmp_path):
    from pathlib import Path
    from PySide6.QtCore import QPointF, QUrl, Qt
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    from shiboken6 import delete
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    from test_measurement_qml import _visual_children

    settings = SettingsController(path=tmp_path / 'settings.json')
    window = QQuickView()
    window.engine().addImageProvider('navigation', SvgIconProvider())
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.setInitialProperties({'settingsController': settings})
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/settings/ToolbarSettingsPage.qml')))
    assert window.status() == QQuickView.Ready
    window.resize(940, 720)
    window.show()
    QTest.qWait(80)
    editor = window.rootObject().property('editor')

    def item(name):
        return next(i for i in _visual_children(window.rootObject()) if i.objectName() == name and i.isVisible())

    def click(name):
        target = item(name)
        pos = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
        QTest.qWait(30)

    try:
        click('toolbarTile-common-scroll')
        click('toolbarUp-common-scroll')
        assert editor.commonTools[0]['toolType'] == 'scroll'
        assert settings.section('toolbar')['rightProfiles'] == {}
        click('toolbarCancel')
        assert editor.commonTools[0]['toolType'] == 'window'
        handle = item('toolbarDrag-common-window')
        start = handle.mapToScene(QPointF(handle.width()/2, handle.height()/2)).toPoint()
        destination = item('toolbarTile-common-pan')
        end = destination.mapToScene(QPointF(destination.width() * .8, destination.height() / 2)).toPoint()
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        for n in range(1, 9):
            QTest.mouseMove(window, start + (end-start)*n/8, 15)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
        QTest.qWait(40)
        assert [t['toolType'] for t in editor.commonTools][:3] == ['scroll','pan','window']
        click('toolbarSave')
        assert settings.section('toolbar')['rightProfiles']['2d:ct']['common'][:3] == ['scroll','pan','window']
        assert window.grabWindow().save(str(tmp_path/'toolbar-editor.png'))
        click('toolbarRestore')
        assert editor.commonTools[0]['toolType'] == 'window'
        click('toolbarCancel')
        assert editor.commonTools[0]['toolType'] == 'scroll'
        assert not warnings, warnings
    finally:
        window.close()
        delete(window)


def test_live_toolbar_order_and_collapsed_custom_panel_reachability(sidebar_scene, tmp_path, monkeypatch):
    from test_mpr_volume_tools_qml import item_window
    from PySide6.QtTest import QTest
    from test_tag_qml import find, click, descendants
    from test_dicom_tags import wait_until
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'CT', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    assert app.settingsController.setValue('toolbar', 'leftViews', ['3d','mpr','2d'])
    assert app.settingsController.setValue('toolbar', 'rightProfiles', {
        'mpr:ct': {'common':['import','segmentation','zoom','window'], 'more':['export','pan','measure']}})
    QTest.qWait(80)
    names = [i.objectName() for i in descendants(window.contentItem()) if i.isVisible() and i.objectName().startswith('openView-')]
    assert names[:3] == ['openView-3d','openView-mpr','openView-2d']
    names = [i.objectName() for i in descendants(window.contentItem()) if i.isVisible() and i.objectName().startswith('primaryTool-')]
    assert names == ['primaryTool-import','primaryTool-segmentation','primaryTool-zoom','primaryTool-window']
    app.settingsController.setValue('layout', 'rightPanelCollapsed', True)
    QTest.qWait(80)
    names = [i.objectName() for i in descendants(window.contentItem()) if i.isVisible() and i.objectName().startswith('compactTool-')]
    assert names[:7] == ['compactTool-import','compactTool-segmentation','compactTool-zoom','compactTool-window','compactTool-export','compactTool-pan','compactTool-measure']
    click(window, find(window, 'compactTool-import'))
    assert workspace.activeTab.toolController.activePanel == 'import'
    popup = window.findChild(QObject, 'compactVolumePanel')
    assert popup.property('visible') and popup.property('panelTool') == 'import'
    popup_window = item_window(popup.property('contentItem'))
    import_panel = find(popup_window, 'associatedImportPanel')
    assert import_panel.property('controller') == app.exportController.dicomResults
    requests = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.dicom_results_controller.QFileDialog.getOpenFileName',
                        lambda *args: (requests.append(args) or ('', '')))
    import_button = find(popup_window, 'importSegmentation')
    assert import_button.isEnabled()
    click(popup_window, import_button)
    assert len(requests) == 1
    click(popup_window, find(popup_window, 'compactVolumePanelClose'))
    click(window, find(window, 'compactTool-export'))
    popup_window = item_window(popup.property('contentItem'))
    export_panel = find(popup_window, 'exportPanel')
    assert export_panel.property('exportController') == app.exportController
    assert export_panel.property('exportItem') is not None
    export_folder = tmp_path / 'exported'
    export_folder.mkdir()
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.export_controller.QFileDialog.getExistingDirectory',
                        lambda *args: str(export_folder))
    click(popup_window, find(popup_window, 'exportDicom'))
    wait_until(lambda: not app.exportController.busy)
    assert not app.exportController.isError, app.exportController.message
    assert len(list(export_folder.rglob('*.dcm'))) == 3
    assert window.grabWindow().save(str(tmp_path / 'custom-compact-import.png'))
    assert not warnings, warnings


def test_two_editors_keep_independent_drafts(qt_app):
    settings = SettingsController(path=False)
    assert hasattr(settings, 'createToolbarEditor')
    first, second = settings.createToolbarEditor(settings), settings.createToolbarEditor(settings)
    first.moveLeftView(2, 0)
    second.beginEdit()
    second.moveTool('common', 1, 0)
    second.cancel()
    assert first.leftViews[0]['toolType'] == '3d'
    assert second.leftViews[0]['toolType'] == '2d'


def test_full_settings_toolbar_controls_remain_visible(sidebar_scene, tmp_path):
    from pathlib import Path
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    from test_tag_qml import find, click
    window, app, _, warnings = sidebar_scene
    app.languageController.selectLanguage('en-US')
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('toolbar')
    window.resize(1280, 720)
    QTest.qWait(100)
    click(window, find(window, 'toolbarTile-common-scroll'))
    click(window, find(window, 'toolbarUp-common-scroll'))
    assert find(window, 'toolbarProfile').property('displayText') == '2D reading'
    for width in (1600, 1280):
        window.resize(width, 720)
        QTest.qWait(80)
        for name in ('toolbarSave', 'toolbarCancel', 'toolbarRestore', 'toolbarProfile'):
            control = find(window, name)
            position = control.mapToScene(QPointF())
            assert 0 <= position.x() and position.x() + control.width() <= window.width()
            assert 0 <= position.y() and position.y() + control.height() <= window.height()
        assert find(window, 'toolbarTile-common-scroll').width() >= 75
        target = Path('build/toolbar-visual') / f'toolbar-settings-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        assert window.grabWindow().save(str(target))
    click(window, find(window, 'toolbarSave'))
    assert app.settingsController.section('toolbar')['rightProfiles']['2d:ct']['common'][0] == 'scroll'
    assert not warnings, warnings
