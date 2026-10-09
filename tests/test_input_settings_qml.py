from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPointF, QObject
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants


def visible_viewport(window):
    def candidates():
        return [i for i in descendants(window.contentItem())
                if i.objectName() == 'viewportInteractionLayer' and i.isVisible()]
    wait_until(lambda: bool(candidates()))
    return candidates()[0]


def reading_scene(scene):
    window, app, records, warnings = scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    window.requestActivate()
    QTest.qWait(100)
    viewport = visible_viewport(window)
    click(window, viewport)
    return window, app, ws.activeTab


def test_tool_keys_respect_text_focus_modal_and_remapping(sidebar_scene, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    tools = tab.toolController
    QTest.keyClick(window, Qt.Key_P)
    assert tools.activeInteraction == 'pan'
    QTest.keyClick(window, Qt.Key_W)
    assert tools.activeInteraction == 'window'
    search = find(window, 'sidebarPatientSearch')
    click(window, search)
    QTest.keyClick(window, Qt.Key_P)
    assert tools.activeInteraction == 'window'
    assert 'p' in search.property('text').lower()
    search.setProperty('text','')
    viewport = visible_viewport(window)
    click(window, viewport)
    assert app.shortcutController.assign('pan','Shift+P')
    QTest.qWait(30)
    QTest.keyClick(window, Qt.Key_P)
    assert tools.activeInteraction == 'window'
    QTest.keyClick(window, Qt.Key_P, Qt.ShiftModifier)
    assert tools.activeInteraction == 'pan'
    # Popup blocks tool keys even though the image retains its selected tool.
    app.feedbackController.show()
    QTest.qWait(50)
    assert window.property('shortcutPopupOpen')
    QTest.keyClick(window, Qt.Key_W)
    assert tools.activeInteraction == 'pan'
    assert not sidebar_scene[3], sidebar_scene[3]
    assert window.grabWindow().save(str(tmp_path/'shortcut-modal.png'))


def test_settings_record_conflicts_privacy_and_scale(sidebar_scene, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    QTest.qWait(60)
    click(window, find(window,'shortcutRecord-pan'))
    assert app.shortcutController.recordingAction=='pan'
    QTest.keyClick(window, Qt.Key_W)
    assert app.settingsController.messageIsError
    assert app.shortcutController.recordingAction=='pan'
    QTest.keyClick(window, Qt.Key_P, Qt.ShiftModifier)
    assert app.shortcutController.recordingAction==''
    assert app.shortcutController.hint('pan')
    assert window.grabWindow().save(str(tmp_path/'input-settings.png'))
    app.settingsController.selectCategory('privacy')
    QTest.qWait(30)
    click(window, find(window,'privacyHideIdentity'))
    assert app.settingsController.section('privacy')['hideIdentity']
    assert not tab.activeViewport.hideSensitiveInfo  # existing view keeps its choice
    assert window.grabWindow().save(str(tmp_path/'privacy-settings.png'))
    app.settingsController.selectCategory('appearance')
    QTest.qWait(30)
    combo=find(window,'interfaceSize')
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    assert app.settingsController.section('appearance')['interfaceScale']==115
    assert window.grabWindow().save(str(tmp_path/'size-settings.png'))
    app.workspaceController.createTab(sidebar_scene[2][1].series_instance_uid,'CT','2d')
    wait_until(lambda: app.workspaceController.activeLoadState.status=='ready')
    assert app.workspaceController.activeViewport.hideSensitiveInfo
    assert not sidebar_scene[3], sidebar_scene[3]


def test_shortcuts_only_target_focused_window_and_do_not_repeat(sidebar_scene):
    from test_tab_windows import detached
    window, app, first = reading_scene(sidebar_scene)
    ws=app.workspaceController
    ws.createTab(sidebar_scene[2][1].series_instance_uid,'CT','2d')
    wait_until(lambda: ws.activeLoadState.status=='ready')
    second=ws.activeTab
    session, other=detached(app,first)
    other.requestActivate(); QTest.qWait(100)
    viewport=visible_viewport(other)
    click(other,viewport)
    QTest.keyClick(other,Qt.Key_P)
    assert first.toolController.activeInteraction=='pan'
    assert second.toolController.activeInteraction=='window'
    window.requestActivate(); QTest.qWait(80)
    viewport=visible_viewport(window)
    click(window,viewport)
    QTest.keyClick(window,Qt.Key_Z)
    assert second.toolController.activeInteraction=='zoom'
    assert first.toolController.activeInteraction=='pan'
    assert not sidebar_scene[3],sidebar_scene[3]


def test_mpr_brush_erase_shortcuts_and_history(sidebar_scene):
    window,app,records,warnings=sidebar_scene
    ws=app.workspaceController
    ws.createTab(records[0].series_instance_uid,'CT','mpr')
    wait_until(lambda: ws.activeLoadState.status=='ready')
    window.requestActivate(); QTest.qWait(80)
    viewport=visible_viewport(window)
    click(window,viewport)
    QTest.keyClick(window,Qt.Key_B)
    tab=ws.activeTab
    assert tab.toolController.activeTool=='segmentation'
    assert tab.voiController.editMode=='paint'
    QTest.keyClick(window,Qt.Key_E)
    assert tab.voiController.editMode=='erase'
    # Returning to a different tool does not modify the mask.
    count=len(tab.voiController.items)
    QTest.keyClick(window,Qt.Key_W)
    assert tab.toolController.activeInteraction=='window'
    assert len(tab.voiController.items)==count
    assert not warnings,warnings


def test_privacy_saved_view_wins_and_clear_history_keeps_files(sidebar_scene,tmp_path):
    window,app,tab=reading_scene(sidebar_scene)
    manager=app.workspaceDocumentController
    path=tmp_path/'privacy.voxworkspace'
    assert not tab.activeViewport.hideSensitiveInfo
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError,manager.message
    app.settingsController.setValue('privacy','hideIdentity',True)
    assert manager.restore_from(path)
    wait_until(lambda: not manager.busy,timeout=20000)
    assert not manager.isError,manager.message
    assert not app.workspaceController.activeViewport.hideSensitiveInfo
    assert manager.recentWorkspaces
    app.workspaceController.openSettings();app.settingsController.selectCategory('privacy')
    QTest.qWait(50)
    click(window,find(window,'clearRecentWorkspaces'))
    assert not manager.recentWorkspaces and path.is_file()
    from qt_dicom_viewer.infrastructure.recent_workspaces import RecentWorkspaces
    assert not RecentWorkspaces(manager._recent.path).items
    assert not sidebar_scene[3],sidebar_scene[3]


def test_recording_consumes_reserved_keys_and_cancels(sidebar_scene):
    from PySide6.QtCore import QCoreApplication, QEvent
    window, app, tab = reading_scene(sidebar_scene)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    QTest.qWait(60)
    click(window, find(window, 'shortcutRecord-pan'))
    QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
    assert app.shortcutController.recordingAction == 'pan'
    assert app.settingsController.messageIsError
    assert not window.property('shortcutPopupOpen')  # no save dialog
    QTest.keyClick(window, Qt.Key_Escape)
    assert app.shortcutController.recordingAction == ''
    click(window, find(window, 'shortcutRecord-pan'))
    QCoreApplication.sendEvent(window, QEvent(QEvent.WindowDeactivate))
    assert app.shortcutController.recordingAction == ''
    assert app.shortcutController.hint('pan') == 'P'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_recording_click_away_restores_binding_and_keeps_click(sidebar_scene):
    from test_settings_redesign import reveal_setting
    window, app, tab = reading_scene(sidebar_scene)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    QTest.qWait(60)
    original = dict(app.settingsController.section('shortcuts')['bindings'])
    record = find(window, 'shortcutRecord-pan')
    reveal_setting(window, record)
    click(window, record)
    assert record.property('checked')
    # A heading has no focus policy: losing focus alone is not sufficient.
    click(window, find(window, 'settingsHeading'))
    assert app.shortcutController.recordingAction == ''
    assert record.property('text') == 'P' and not record.property('checked')
    click(window, record)
    search = find(window, 'settingsSearch')
    click(window, search)
    QTest.keyClick(window, Qt.Key_X)
    assert search.property('text').lower() == 'x'
    search.setProperty('text', '')
    click(window, record)
    click(window, find(window, 'shortcutRecord-zoom'))
    assert app.shortcutController.recordingAction == 'zoom'
    QTest.keyClick(window, Qt.Key_Escape)
    assert app.settingsController.section('shortcuts')['bindings'] == original
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('theme,locale', [('dark','zh-CN'), ('graphite','zh-CN'), ('light','en-US')])
def test_input_page_readonly_left_and_key_badges(sidebar_scene, tmp_path, theme, locale):
    window, app, tab = reading_scene(sidebar_scene)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    window.resize(1280, 720)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    QTest.qWait(80)
    left = find(window, 'mouseBinding-leftButton')
    assert not left.isEnabled()
    assert left.property('currentIndex') == 0
    assert find(window, 'mouseBinding-middleButton').isEnabled()
    assert find(window, 'mouseBinding-middleButton').property('displayText') == left.property('displayText')
    assert window.grabWindow().save(str(tmp_path/'mouse-bindings.png'))
    scroll = find(window, 'displaySettingsScroll').property('contentItem')
    scroll.setProperty('contentY', max(0, scroll.property('contentHeight') - scroll.height()))
    QTest.qWait(80)
    for action in ('open', 'save', 'undo', 'redo', 'fullscreen'):
        badge = find(window, 'fixedShortcutBadge-' + action)
        assert badge.width() >= 100 and badge.height() == 30
        assert badge.property('color').alpha() > 0
        pos = badge.mapToItem(scroll, QPointF())
        assert pos.x() >= 0 and pos.x()+badge.width() <= scroll.width()
    assert window.grabWindow().save(str(tmp_path/'basic-shortcuts.png'))
    assert not sidebar_scene[3], sidebar_scene[3]
