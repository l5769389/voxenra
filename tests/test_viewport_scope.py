"""Per-cell display controls, Compare shortcut and recovery popup lifecycle."""
from pathlib import Path
from threading import Event
import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_compare_2d import comparison
from test_two_d_layout import open_scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from voxplane.ui.controller.viewport.image_2d.image_2d_viewport_controller import VIEWPORT_SETTING_FIELDS


@pytest.mark.parametrize('code', ['window-annotations', 'hide-sensitive-info', 'scale-bar',
                                  'color-bar', 'dicom-overlay', 'fit-to-window'])
def test_current_cell_and_tab_defaults_are_isolated_and_inherited(comparison, code):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    second = tab.activeViewport
    wait_until(lambda: second.loadState == 'ready')
    first = layout.cells[0]['viewport']
    field = VIEWPORT_SETTING_FIELDS[code]
    # Resolve inherited corner visibility when checking effective checkbox state.
    original = first.showWindowAnnotations if code == "window-annotations" else getattr(first._state.display_settings, field)
    if code == "window-annotations":
        first.setViewportSetting(code, original)
    layout.setViewportSetting(code, not original)
    assert getattr(first._state.display_settings, field) == original
    assert getattr(second._state.display_settings, field) != original
    layout.setMode(1, 'axial')
    plane = tab.activeViewport
    wait_until(lambda: plane.loadState == 'ready')
    assert getattr(plane._state.display_settings, field) != original
    layout.setSettingsScope('tab')
    assert layout.viewportSettingStates[code] == 1  # mixed
    layout.setViewportSetting(code, not original)
    assert layout.viewportSettingStates[code] == (0 if original else 2)
    assert all(getattr(v._state.display_settings, field) != original for v in tab.viewports_by_id.values())
    layout.setLayout('2x2')
    # Unloaded cells and subsequently loaded images inherit the tab defaults.
    assert layout.viewportSettingStates[code] == (0 if original else 2)
    layout.loadSeries(3, records[2].series_instance_uid)
    assert getattr(tab.activeViewport._state.display_settings, field) != original
    app.workspaceController.createTab(records[2].series_instance_uid, 'Separate', '2d')
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    new_view = app.workspaceController.activeViewport
    assert (new_view.showWindowAnnotations if code == "window-annotations" else getattr(new_view._state.display_settings, field)) == original


def test_scope_settings_survive_workspace_recovery(comparison, tmp_path):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setSettingsScope('tab')
    layout.setViewportSetting('scale-bar', False)
    layout.setLayout('1x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    layout.setSettingsScope('current')
    layout.setViewportSetting('hide-sensitive-info', True)
    manager = app.workspaceDocumentController
    path = tmp_path / 'scoped.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    assert manager.restore_from(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    restored = app.workspaceController.activeTab
    cells = restored.twoDLayout.cells
    assert not cells[0]['viewport'].showScaleBar and not cells[1]['viewport'].showScaleBar
    assert not cells[0]['viewport'].hideSensitiveInfo and cells[1]['viewport'].hideSensitiveInfo
    restored.twoDLayout.setLayout('2x2')
    restored.twoDLayout.loadSeries(3, records[2].series_instance_uid)
    assert not restored.activeViewport.showScaleBar and not restored.activeViewport.hideSensitiveInfo


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_scoped_checkboxes_mixed_state_and_2d_localizer_visibility(sidebar_scene, theme, tmp_path):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    click(window, find(window, 'primaryTool-viewport-settings'))
    click(window, find(window, 'viewportSetting-scale-bar'))
    assert not tab.activeViewport.showScaleBar and layout.cells[0]['viewport'].showScaleBar
    click(window, find(window, 'viewportScope-tab'))
    checkbox = find(window, 'viewportSetting-scale-bar')
    assert checkbox.property('checkState') == Qt.PartiallyChecked
    assert find(window, 'viewportSetting-dicom-overlay').property('text') == '方向标记'
    assert not any(i.objectName() == 'viewportSetting-localizer' and i.isVisible() for i in descendants(window.contentItem()))
    assert window.grabWindow().save(str(tmp_path / (theme + '-scope.png')))
    click(window, checkbox)
    assert all(c['viewport'].showScaleBar for c in layout.cells)
    click(window, checkbox)
    assert not any(c['viewport'].showScaleBar for c in layout.cells)
    layout.setMode(1, 'coronal')
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    assert not tab.activeViewport.showScaleBar
    assert not any(i.objectName() == 'viewportSetting-localizer' and i.isVisible() for i in descendants(window.contentItem()))
    app.workspaceController.createTab(records[0].series_instance_uid, 'MPR', 'mpr')
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    click(window, find(window, 'primaryTool-viewport-settings'))
    assert find(window, 'viewportSetting-localizer').isVisible()
    assert not warnings, warnings


@pytest.mark.parametrize('selected_count', [0, 1, 2])
def test_compare_shortcut_uses_selection_or_current_view(sidebar_scene, selected_count):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    panel = app.panelController
    if selected_count:
        panel.selectSeries(records[1].series_instance_uid)
    if selected_count == 2:
        panel.selectSeriesWithModifiers(records[2].series_instance_uid, True)
    click(window, find(window, 'imageViewport-' + tab.activeViewport.viewportId))
    QTest.keyClick(window, Qt.Key_D, Qt.ControlModifier)
    if selected_count == 2:
        wait_until(lambda: app.workspaceController.activeTabType == 'compare2d')
        assert {m.series_uid for m in app.workspaceController.activeTab.tab_config.series_metas} == {
            r.series_instance_uid for r in records[1:]}
    else:
        wait_until(lambda: panel.compareController.dialogOpen)
        assert panel.compareController.anchor['seriesUid'] == records[selected_count].series_instance_uid
        panel.compareController.cancel()
    assert not warnings, warnings


def test_recover_closes_popup_immediately_and_errors_can_reopen_it(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    assert manager.save_to(manager._recovery_path, recovery=True)
    wait_until(lambda: not manager.busy)
    manager._previous_recovery = True
    manager.changed.emit()
    monkeypatch.setattr(manager, '_confirm_replace', lambda path: True)
    import voxplane.ui.controller.workspace_document_controller as module
    real_read = module.read_document
    entered, release = Event(), Event()
    def slow_read(path):
        entered.set()
        release.wait(5)
        return real_read(path)
    monkeypatch.setattr(module, 'read_document', slow_read)
    dialog = window.findChild(QObject, 'workspaceDocumentDialog')
    click(window, find(window, 'sidebarWorkspace'))
    wait_until(lambda: dialog.property('visible'))
    native = dialog.findChild(QObject, 'workspaceDocumentMessage').window()
    try:
        click(native, dialog.findChild(QObject, 'recoverWorkspace'))
        wait_until(entered.is_set)
        assert manager.restoring
        wait_until(lambda: not dialog.property('visible'))
        manager.progress.emit('Still restoring')
        QTest.qWait(30)
        assert not dialog.property('visible')
    finally:
        release.set()
    wait_until(lambda: not manager.busy)
    assert not manager.isError and not dialog.property('visible')
    # Invalid or unavailable sources must still expose the recovery controls.
    assert manager.restore_from(Path(manager.recoveryPath).with_name('missing.voxworkspace'))
    wait_until(lambda: not manager.busy)
    assert manager.isError
    wait_until(lambda: dialog.property('visible'))
    assert not warnings, warnings


@pytest.mark.parametrize("action", ["recover", "discard"])
def test_recovery_actions_close_workspace_before_action(sidebar_scene, monkeypatch, action):
    window, app, records, warnings = sidebar_scene
    open_scene(app, records)
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    assert manager.save_to(manager._recovery_path, recovery=True)
    wait_until(lambda: not manager.busy)
    manager._previous_recovery = True
    manager.changed.emit()
    dialog = window.findChild(QObject, "workspaceDocumentDialog")
    click(window, find(window, "sidebarWorkspace"))
    wait_until(lambda: dialog.property("visible"))
    if action == "recover":
        seen = []
        def decline_replace(path):
            seen.append(dialog.property("visible"))
            return False
        monkeypatch.setattr(manager, "_confirm_replace", decline_replace)
    button = dialog.findChild(QObject, "recoverWorkspace" if action == "recover" else "discardWorkspaceRecovery")
    click(button.window(), button)
    wait_until(lambda: not dialog.property("visible"))
    if action == "recover":
        assert seen == [False]  # Closed before opening any replacement confirmation.
        assert manager.recoveryAvailable and not manager.restoring
        assert manager._recovery_path.exists()
    else:
        assert not manager.recoveryAvailable and not manager._recovery_path.exists()
    click(window, find(window, "sidebarWorkspace"))
    wait_until(lambda: dialog.property("visible"))
    assert not warnings, warnings


def test_corner_visibility_inherits_global_until_overridden_and_restores(comparison, tmp_path):
    app, records = comparison
    tab, layout = open_scene(app, records)
    settings = app.settingsController
    first = tab.activeViewport
    settings.setValue('corners', 'enabled', False)
    assert not first.showWindowAnnotations
    layout.setViewportSetting('window-annotations', True)
    assert first.showWindowAnnotations
    layout.setLayout('1x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    second = tab.activeViewport
    wait_until(lambda: second.loadState == 'ready')
    assert not second.showWindowAnnotations
    assert layout.viewportSettingStates['window-annotations'] == 0
    settings.setValue('corners', 'enabled', True)
    assert first.showWindowAnnotations and second.showWindowAnnotations
    layout.setViewportSetting('window-annotations', False)
    settings.setValue('corners', 'enabled', False)
    settings.setValue('corners', 'enabled', True)
    assert first.showWindowAnnotations and not second.showWindowAnnotations
    manager = app.workspaceDocumentController
    target = tmp_path / 'corners.voxworkspace'
    assert manager.save_to(target)
    wait_until(lambda: not manager.busy)
    assert manager.restore_from(target)
    wait_until(lambda: not manager.busy)
    restored = app.workspaceController.activeTab.twoDLayout
    assert restored.cells[0]['viewport'].showWindowAnnotations
    assert not restored.cells[1]['viewport'].showWindowAnnotations
