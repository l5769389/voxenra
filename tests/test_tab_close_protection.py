"""Tab close decisions preserve live edits and recovery until explicitly accepted."""
import pytest
from PySide6.QtCore import QTimer, QPointF, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qt_dicom_viewer.core.workspace_document import read_document
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_series_sidebar import sidebar_scene
from test_tab_windows import open_tabs, detached


@pytest.fixture
def edited_app(qt_app, tmp_path):
    app, record = populated_app(tmp_path, settings_path=tmp_path / "settings.json")
    app.workspaceDocumentController._autosave.stop()
    draw_length(app.workspaceController.activeViewport)
    try:
        yield app
    finally:
        app.shutdown()


def test_cancel_close_preserves_tab_history_dirty_state_and_recovery(edited_app, monkeypatch):
    app = edited_app
    workspace, document = app.workspaceController, app.workspaceDocumentController
    tab, key = workspace.activeTab, workspace.activeTabId
    document._save_recovery()
    wait_until(lambda: not document.busy)
    before = document._recovery_path.read_bytes()
    history = tab.historyController
    dirty = document.dirty
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    workspace.closeTab(key)
    assert workspace.activeTab is tab
    assert tab.historyController is history and history.canUndo
    assert document.dirty is dirty
    assert document._recovery_path.read_bytes() == before
    document._save_recovery()
    wait_until(lambda: not document.busy)
    saved = read_document(document._recovery_path)["tabs"]
    assert len(saved) == 1
    assert any(view["measurements"] for view in saved[0]["edits"]["views"].values())


def test_confirm_close_removes_tab_from_next_recovery(edited_app, monkeypatch):
    app = edited_app
    workspace, document = app.workspaceController, app.workspaceDocumentController
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Close)
    workspace.closeTab(workspace.activeTabId)
    assert not workspace.tabs
    document._save_recovery()
    wait_until(lambda: not document.busy)
    assert read_document(document._recovery_path)['tabs'] == []


def test_saved_and_restored_edits_still_require_close_confirmation(edited_app, tmp_path, monkeypatch):
    app = edited_app
    workspace, document = app.workspaceController, app.workspaceDocumentController
    path = tmp_path / 'saved.voxworkspace'
    assert document.save_to(path)
    wait_until(lambda: not document.busy)
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('Restore cleanup prompted'))
    assert document.restore_from(path)
    wait_until(lambda: not document.busy)
    assert not document.isError and not document.dirty
    tab = workspace.activeTab
    assert not tab.historyController.canUndo
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    workspace.closeTab(workspace.activeTabId)
    assert workspace.activeTab is tab and not document.dirty


def test_bulk_close_cancel_keeps_clean_and_edited_tabs(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    draw_length(tabs[1].activeViewport)
    session = app.windowManager.mainWorkspace
    ids = list(session._ids)
    active = session.activeTab
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    session.closeTabs(ids[0], 'all')
    assert session._ids == ids
    assert session.activeTab is active
    assert len(tabs[1].activeViewport._measure_controller._measurements) == 1


def test_detached_window_cancel_keeps_window_and_edits(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    first, _ = open_tabs(app, records[:2])
    draw_length(first.activeViewport)
    session, other = detached(app, first)
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    assert not other.close()
    assert other.isVisible() and session.activeTab is first
    assert session.windowId in app.windowManager.sessions


def test_clean_and_utility_tabs_close_without_confirmation(qt_app, tmp_path, monkeypatch):
    app, _ = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        workspace.openSettings()
        workspace.openManual()
        workspace.openPacs()
        monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('Clean tab prompted'))
        app.windowManager.mainWorkspace.closeTabs(workspace.activeTabId, 'all')
        assert not workspace.tabs
    finally:
        app.shutdown()


def test_close_dialog_defaults_to_cancel_and_escape_preserves_edits(edited_app):
    workspace = edited_app.workspaceController
    tab = workspace.activeTab
    observed = []
    def dismiss():
        box = next(w for w in QApplication.topLevelWidgets()
                   if w.objectName() == 'tabCloseConfirmation')
        observed.append(box.defaultButton() == box.button(QMessageBox.Cancel))
        QTest.keyClick(box, Qt.Key_Escape)
    QTimer.singleShot(50, dismiss)
    workspace.closeTab(workspace.activeTabId)
    assert workspace.activeTab is tab
    assert observed == [True]


@pytest.mark.parametrize('kind', ['annotation', 'voi', 'segmentation'])
def test_nonmeasurement_edits_cancel_close_without_undo_history(qt_app, tmp_path, monkeypatch, kind):
    from test_mpr_voi_controller import draw
    app, record = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        if kind == 'annotation':
            tab = workspace.activeTab
            tab.activeViewport._text_annotation_controller.addAnnotation(1, 1, 5, 5)
            assert tab.activeViewport._text_annotation_controller._annotations
        else:
            workspace.createTab(record.series_instance_uid, 'MPR', 'mpr')
            wait_until(lambda: workspace.activeLoadState.status == 'ready')
            tab = workspace.activeTab
            if kind == 'segmentation':
                tab._voi_controller.newSegment()
            else:
                tab.toolController.activateTool('voi')
                draw(tab._voi_controller, tab.activeViewport)
            assert tab._voi_controller.records
        tab.historyController.reset()
        monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
        workspace.closeTab(tab.tab_config.tab_id)
        assert workspace.activeTab is tab
    finally:
        app.shutdown()


@pytest.mark.parametrize('gesture', ['button', 'middle', 'shortcut', 'viewport'])
def test_visible_tab_close_gestures_respect_cancel(sidebar_scene, monkeypatch, gesture):
    from test_tag_qml import find
    window, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    draw_length(tab.activeViewport)
    key = tab.tab_config.tab_id
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    if gesture == 'viewport':
        tab.closeRequested.emit()
    elif gesture == 'button':
        target = find(window, 'workspaceTab-' + key)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                         target.mapToScene(QPointF(target.width() - 18, 15)).toPoint())
    elif gesture == 'middle':
        target = find(window, 'workspaceTab-' + key)
        QTest.mouseClick(window, Qt.MiddleButton, Qt.NoModifier,
                         target.mapToScene(QPointF(30, 15)).toPoint())
    else:
        window.requestActivate()
        QTest.qWait(30)
        QTest.keySequence(window, QKeySequence(QKeySequence.StandardKey.Close))
    assert app.workspaceController.activeTab is tab
    assert find(window, 'workspaceTab-' + key).isVisible()
    assert len(tab.activeViewport._measure_controller._measurements) == 1


def test_nested_close_cannot_bypass_pending_confirmation(edited_app, monkeypatch):
    workspace = edited_app.workspaceController
    tab, key = workspace.activeTab, workspace.activeTabId
    def prompt(self):
        assert not workspace.closeTab(key)
        return QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox, 'exec', prompt)
    workspace.closeTab(key)
    assert workspace.activeTab is tab


def test_mpr_comparison_group_segment_requires_confirmation(sidebar_scene, monkeypatch):
    from test_compare_mpr import open_pair
    window, app, records, warnings = sidebar_scene
    tab = open_pair(app, records)
    group = tab.groups[1]
    group._voi_controller.newSegment()
    assert group._voi_controller.records
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
    app.workspaceController.closeTab(tab.tab_config.tab_id)
    assert app.workspaceController.activeTab is tab


def test_close_dialog_follows_theme_language_and_owner(sidebar_scene, monkeypatch):
    from PySide6.QtGui import QColor, QPalette
    window, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    draw_length(tab.activeViewport)
    checked = []
    def inspect(box):
        for theme, locale in [('light', 'en-US'), ('dark', 'zh-CN')]:
            app.settingsController.setValue('appearance', 'theme', theme)
            app.languageController.selectLanguage(locale)
            QTest.qWait(40)
            assert box.palette().color(QPalette.Window) == QColor(app.appearanceController.colors['panelBackground'])
            assert box.button(QMessageBox.Close).text() == ('Close and remove edits' if locale == 'en-US' else '关闭并移除编辑结果')
        assert box.windowHandle().transientParent() is window
        checked.append(True)
        return QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox, 'exec', inspect)
    app.workspaceController.closeTab(tab.tab_config.tab_id)
    assert checked and app.workspaceController.activeTab is tab


@pytest.mark.parametrize('kind,completed', [
    ('mtf', False), ('fwhm', False), ('mtf', True), ('fwhm', True), ('qa', True)])
def test_analysis_only_work_requires_close_confirmation(qt_app, tmp_path, monkeypatch, kind, completed):
    from test_mtf_controller import bead_render, deliver_frame
    from test_water_qa_controller import water_render
    app, _ = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        tab, view = workspace.activeTab, workspace.activeViewport
        deliver_frame(view, water_render(view) if kind == 'qa' else bead_render(view))
        controller = getattr(view, '_' + kind + '_controller')
        if kind == 'qa':
            tab.toolController.selectService('service:qa')
        else:
            assert controller.applyRoi(63, 63, 8, 3)
        if completed:
            wait_until(lambda: controller.status != 'calculating')
            assert controller.status == 'ready', controller.error
            assert controller.persistent_state()['records']
        else:
            saved = controller.persistent_state()
            assert saved['roi']['measurements'] and not saved['records']
        assert not view._measure_controller._measurements
        tab.historyController.reset()
        monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Cancel)
        workspace.closeTab(tab.tab_config.tab_id)
        assert workspace.activeTab is tab
    finally:
        app.shutdown()


def test_untouched_analysis_defaults_do_not_require_confirmation(qt_app, tmp_path, monkeypatch):
    app, _ = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        view = workspace.activeViewport
        for kind in ('mtf', 'fwhm', 'qa'):
            saved = getattr(view, '_' + kind + '_controller').persistent_state()
            assert saved and not saved['records']
            assert not saved.get('roi', {}).get('measurements')
        monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('Untouched analysis defaults prompted'))
        workspace.closeTab(workspace.activeTabId)
        assert not workspace.tabs
    finally:
        app.shutdown()
