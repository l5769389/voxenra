"""Real new-workspace entry points and theme-aware unsaved-work decisions."""
import pytest
from PySide6.QtCore import QObject, QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_workspace_dialog_layout import workspace_dialog


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_dialog_new_cancel_then_discard_returns_empty_home(sidebar_scene, tmp_path, locale, theme):
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'theme', theme)
    doc, ws = app.workspaceDocumentController, app.workspaceController
    doc._autosave.stop()
    ws.createTab(records[0].series_instance_uid, 'Image', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    dialog, native = workspace_dialog(window)
    button = dialog.findChild(QObject, 'newWorkspace')
    assert button.isVisible() and button.isEnabled()
    assert button.width() >= button.implicitWidth()
    native.grabWindow().save(str(tmp_path / f'new-workspace-{locale}-{theme}.png'))
    decisions = []
    def choose(role):
        alert = QApplication.activeModalWidget()
        if alert is None:
            decisions.append('missing confirmation')
            return
        decisions.append((alert.objectName(), alert.checkBox() is None))
        alert.grab().save(str(tmp_path / f'new-confirm-{locale}-{theme}.png'))
        QTest.mouseClick(alert.button(role), Qt.LeftButton)
    QTimer.singleShot(150, lambda: choose(QMessageBox.Cancel))
    click(native, button)
    assert decisions == [('workspaceNewConfirmation', True)]
    assert dialog.property('visible') and ws.activeTab is tab
    QTimer.singleShot(150, lambda: choose(QMessageBox.Discard))
    click(native, button)
    wait_until(lambda: not dialog.property('visible'))
    assert decisions == [('workspaceNewConfirmation', True)] * 2
    assert not doc.hasContent and not doc.path and not doc.dirty
    assert not ws._tab_dict and not app.panelController.seriesItems
    home = find(window, 'workspaceEmptyState')
    wait_until(home.isVisible)
    QTest.qWait(80)
    for name in ('homeNewWorkspace', 'homeOpenWorkspace', 'homeQuickStart', 'homeOpenPacs'):
        control = find(window, name)
        point = control.mapToItem(home, QPointF())
        assert control.width() >= control.implicitWidth()
        assert 0 <= point.x() and point.x() + control.width() <= home.width() + 1
    assert window.grabWindow().save(str(tmp_path / f'blank-home-{locale}-{theme}.png'))
    assert not warnings, warnings


def test_home_and_keyboard_create_new_and_busy_disables_both(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    doc = app.workspaceDocumentController
    doc._autosave.stop()
    prompts = []
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: prompts.append(True) or QMessageBox.Discard)
    click(window, find(window, 'homeNewWorkspace'))
    assert prompts == [True] and not doc.hasContent
    app.workspaceController.openManual()
    window.requestActivate()
    wait_until(window.isActive)
    QTest.keyClick(window, Qt.Key_N, Qt.ControlModifier)
    wait_until(lambda: not app.workspaceController._tab_dict)
    assert find(window, 'workspaceEmptyState').isVisible()
    app.panelController._scanning = True
    app.panelController.scanningChanged.emit()
    assert not find(window, 'homeNewWorkspace').isEnabled()
    assert not window.findChild(QObject, 'newWorkspaceShortcut').property('enabled')
    app.panelController._scanning = False
    app.panelController.scanningChanged.emit()
    assert find(window, 'homeNewWorkspace').isEnabled()
    assert not warnings, warnings


def test_new_closes_detached_tabs_and_returns_to_main(sidebar_scene, monkeypatch):
    from test_tab_windows import detached
    window, app, records, warnings = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    doc._autosave.stop()
    ws.createTab(records[0].series_instance_uid, 'Image', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    session, other = detached(app, ws.activeTab)
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Discard)
    assert doc.newWorkspace()
    wait_until(lambda: not other.isVisible())
    assert not ws._tab_dict and not session.tabs
    assert window.isVisible() and find(window, 'workspaceEmptyState').isVisible()
    assert not warnings, warnings


def test_save_and_create_from_real_confirmation(sidebar_scene, tmp_path, monkeypatch):
    from qt_dicom_viewer.core.workspace_document import read_document
    from test_workspace_persistence import draw_length
    window, app, records, warnings = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    doc._autosave.stop()
    ws.createTab(records[0].series_instance_uid, 'Image', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    draw_length(ws.activeViewport)
    ws.activeTab.historyController.capture()
    path = tmp_path / 'before-new.voxworkspace'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(path), ''))
    dialog, native = workspace_dialog(window)
    def save():
        alert = QApplication.activeModalWidget()
        QTest.mouseClick(alert.button(QMessageBox.Save), Qt.LeftButton)
    QTimer.singleShot(150, save)
    click(native, dialog.findChild(QObject, 'newWorkspace'))
    wait_until(lambda: not doc.busy and not dialog.property('visible'))
    assert not doc.hasContent and not doc.dirty and not doc.path
    assert find(window, 'workspaceEmptyState').isVisible()
    saved = read_document(path)
    assert any(v.get('measurements') for v in saved['tabs'][0]['edits']['views'].values())
    assert not warnings, warnings
