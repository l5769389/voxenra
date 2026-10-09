"""Exit choices persist only after confirmation and a successful save."""
from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qt_dicom_viewer.settings.preferences import normalize_settings
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click
from test_workspace_persistence import populated_app


@pytest.fixture
def exit_app(qt_app, tmp_path, monkeypatch):
    app, _ = populated_app(tmp_path, settings_path=tmp_path / 'settings.json')
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    manager.mark_dirty()
    quits = []
    monkeypatch.setattr(QCoreApplication, 'quit', lambda: quits.append(True))
    try:
        yield app, manager, quits
    finally:
        app.shutdown()


def preference(app):
    return app.settingsController.section('workspace')['exitBehavior']


@pytest.mark.parametrize('behavior', ['ask', 'save', 'discard'])
@pytest.mark.parametrize('content', ['fresh', 'utility-tabs', 'cleared'])
def test_empty_workspace_exits_without_prompt_or_save(qt_app, tmp_path, monkeypatch, behavior, content):
    if content == 'cleared':
        app, record = populated_app(tmp_path, settings_path=tmp_path / 'settings.json')
        app.workspaceController.closeTab(app.workspaceController.activeTabId)
        app.panelController.removeSeries(record.series_instance_uid)
    else:
        app = AppController(DicomImageProvider(), settings_path=tmp_path / 'settings.json')
    manager = app.workspaceDocumentController
    manager._autosave.stop()
    try:
        if content == 'utility-tabs':
            app.workspaceController.openSettings()
            app.workspaceController.openManual()
            app.workspaceController.openPacs()
        manager.setSidebarLayout(250, True)
        app.settingsController.setValue('workspace', 'exitBehavior', behavior)
        assert manager.dirty and not manager.hasContent
        monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: pytest.fail('Empty workspace prompted'))
        monkeypatch.setattr(manager, 'save', lambda: pytest.fail('Empty workspace opened save dialog'))
        manager._save_recovery()
        assert manager.recoveryState == 'idle' and not manager.busy
        assert not manager._recovery_path.exists()
        assert manager.requestClose()
        assert not manager.eventFilter(QCoreApplication.instance(), QEvent(QEvent.Quit))
        assert preference(app) == behavior
    finally:
        app.shutdown()


@pytest.mark.parametrize('remaining', ['sidebar', 'view'])
def test_remaining_series_or_view_still_requires_confirmation(exit_app, monkeypatch, remaining):
    app, manager, _ = exit_app
    if remaining == 'sidebar':
        app.workspaceController.closeTab(app.workspaceController.activeTabId)
    else:
        app.panelController.clearSeries()
    assert manager.hasContent and manager.dirty
    prompts = []
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: prompts.append(True) or ('cancel', False))
    assert not manager.requestClose() and prompts == [True]


def test_exit_preference_migration_validation_and_reset(tmp_path):
    for raw in ({}, {'workspace': {'automaticRecovery': False}},
                {'workspace': {'exitBehavior': 'invalid'}}):
        assert normalize_settings(raw)['workspace']['exitBehavior'] == 'ask'
    settings = SettingsController(path=tmp_path / 'settings.json')
    for value in ('save', 'discard', 'ask'):
        assert settings.setValue('workspace', 'exitBehavior', value)
        assert SettingsController(path=settings._path).section('workspace')['exitBehavior'] == value
    for invalid in (None, True, 1, [], {}, 'never'):
        assert not settings.setValue('workspace', 'exitBehavior', invalid)
        assert settings.section('workspace')['exitBehavior'] == 'ask'
    settings.setValue('workspace', 'exitBehavior', 'discard')
    assert settings.resetSection('workspace')
    assert settings.section('workspace')['exitBehavior'] == 'ask'


@pytest.mark.parametrize('answer,remember,closes,stored', [
    ('cancel', True, False, 'ask'), ('discard', False, True, 'ask'),
    ('discard', True, True, 'discard')])
def test_remember_only_confirmed_exit(exit_app, monkeypatch, answer, remember, closes, stored):
    app, manager, _ = exit_app
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: (answer, remember))
    assert manager.requestClose() is closes
    assert preference(app) == stored
    assert SettingsController(path=app.settingsController._path).section('workspace')['exitBehavior'] == stored


def test_remembered_discard_skips_prompt_until_settings_restore_it(exit_app, monkeypatch):
    app, manager, _ = exit_app
    prompts = []
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: prompts.append(True) or ('cancel', False))
    app.settingsController.setValue('workspace', 'exitBehavior', 'discard')
    assert not manager.eventFilter(QCoreApplication.instance(), QEvent(QEvent.Quit))
    assert not prompts
    manager._quit_approved = False
    app.settingsController.setValue('workspace', 'exitBehavior', 'ask')
    assert not manager.requestClose() and prompts == [True]


@pytest.mark.parametrize('remembered', [False, True])
def test_save_choice_waits_for_file_before_exit(exit_app, tmp_path, monkeypatch, remembered):
    app, manager, quits = exit_app
    target = tmp_path / 'work.voxworkspace'
    manager._path = str(target)
    if remembered:
        app.settingsController.setValue('workspace', 'exitBehavior', 'save')
        monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: pytest.fail('Unexpected exit prompt'))
    else:
        monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: ('save', True))
    assert not manager.requestClose()
    assert not quits
    if not remembered:
        assert preference(app) == 'ask'
    wait_until(lambda: not manager.busy)
    assert target.is_file() and quits == [True] and manager.requestClose()
    assert not manager.dirty
    assert SettingsController(path=app.settingsController._path).section('workspace')['exitBehavior'] == 'save'


@pytest.mark.parametrize('failure', ['cancel', 'write', 'new-edits'])
def test_incomplete_save_does_not_quit_or_remember(exit_app, tmp_path, monkeypatch, failure):
    import qt_dicom_viewer.ui.controller.workspace_document_controller as module
    app, manager, quits = exit_app
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: ('save', True))
    release, entered = Event(), Event()
    write = module.atomic_write
    if failure == 'cancel':
        monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *a: ('', ''))
    else:
        manager._path = str(tmp_path / 'work.voxworkspace')
        def save(path, payload):
            if failure == 'write':
                raise OSError('磁盘空间不足')
            entered.set()
            assert release.wait(5)
            write(path, payload)
        monkeypatch.setattr(module, 'atomic_write', save)
    try:
        assert not manager.requestClose()
        if failure == 'new-edits':
            assert entered.wait(2)
            manager.mark_dirty()
            release.set()
        wait_until(lambda: not manager.busy)
        assert manager.dirty and not quits and preference(app) == 'ask'
        assert not manager._close_after_save and not manager._remember_exit_after_save
        if failure == 'write':
            assert manager.isError and '磁盘空间不足' in manager.message
    finally:
        release.set()


def test_busy_and_nested_close_do_not_open_another_prompt(exit_app, monkeypatch):
    app, manager, _ = exit_app
    def prompt():
        assert not manager.requestClose()
        return 'cancel', True
    monkeypatch.setattr(manager, '_ask_exit_behavior', prompt)
    assert not manager.requestClose()
    manager._busy = True
    assert not manager.requestClose()
    manager._busy = False
    manager._dirty = False
    assert manager.requestClose() and preference(app) == 'ask'


def test_remember_failure_preserves_prompt_and_keeps_app_open(exit_app, tmp_path, monkeypatch):
    app, manager, quits = exit_app
    app.settingsController._path = tmp_path
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: ('discard', True))
    assert not manager.requestClose()
    assert preference(app) == 'ask' and manager.isError
    assert '保存设置失败' in manager.message and not quits


def test_exit_dialog_has_remember_checkbox_and_cancel_does_not_remember(exit_app):
    app, manager, _ = exit_app
    observations = []
    def dismiss():
        box = next(w for w in QApplication.topLevelWidgets() if w.objectName() == 'workspaceExitConfirmation')
        checkbox = box.checkBox()
        observations.append((checkbox.text(), box.defaultButton() == box.button(QMessageBox.Save)))
        checkbox.click()
        box.button(QMessageBox.Cancel).click()
    QTimer.singleShot(100, dismiss)
    assert not manager.requestClose()
    assert observations == [('记住本次选择，下次不再询问', True)]
    assert preference(app) == 'ask'


@pytest.mark.parametrize('named', [False, True])
def test_exit_confirmation_theme_and_document_specific_actions(exit_app, tmp_path, named):
    from qt_dicom_viewer.ui.dialogs.workspace_exit_dialog import WorkspaceExitDialog
    from PySide6.QtGui import QColor, QGuiApplication, QPalette
    app, manager, _ = exit_app
    box = WorkspaceExitDialog(app.appearanceController, workspace_name='复查 <1>' if named else '')
    try:
        box.show()
        for theme, locale in [('light', 'zh-CN'), ('dark', 'zh-CN'), ('dark', 'en-US')]:
            app.settingsController.setValue('appearance', 'theme', theme)
            app.languageController.selectLanguage(locale)
            QTest.qWait(60)
            colors = app.appearanceController.colors
            assert box.testOption(QMessageBox.Option.DontUseNativeDialog)
            if QGuiApplication.platformName() == 'cocoa':
                import ctypes
                from test_window_chrome import _mac_send
                native = _mac_send(int(box.winId()), 'window')
                name = _mac_send(_mac_send(native, 'effectiveAppearance'), 'name')
                assert (b'Dark' in ctypes.string_at(_mac_send(name, 'UTF8String'))) == (theme == 'dark')
            assert box.palette().color(QPalette.Window) == QColor(colors['panelBackground'])
            assert box.button(QMessageBox.Save).palette().color(QPalette.ButtonText) == QColor(colors['textOnPrimary'])
            assert box.textFormat() == Qt.PlainText
            assert box.checkBox().text()
            assert box.grab().save(str(tmp_path / f'exit-{named}-{theme}-{locale}.png'))
            if locale == 'zh-CN':
                assert box.button(QMessageBox.Save).text() == ('更新' if named else '保存工作区…')
                assert box.button(QMessageBox.Discard).text() == ('不更新' if named else '不保存')
                assert box.button(QMessageBox.Cancel).text() == '取消'
                if named:
                    assert box.text() == '是否更新工作区？'
            else:
                assert box.button(QMessageBox.Save).text() == ('Update' if named else 'Save workspace…')
            assert '复查 <1>' not in box.text()
            if named:
                assert not box.informativeText()
        QTest.keyClick(box, Qt.Key_Escape)
        wait_until(lambda: not box.isVisible())
        assert box.result() == QMessageBox.Cancel
    finally:
        box.deleteLater()


def test_opened_workspace_only_prompts_after_edits(exit_app, tmp_path, monkeypatch):
    app, manager, quits = exit_app
    target = tmp_path / 'review.voxworkspace'
    assert manager.save_to(target)
    wait_until(lambda: not manager.busy)
    assert manager.restore_from(target)
    wait_until(lambda: not manager.busy, timeout=20000)
    assert not manager.isError and not manager.dirty
    prompts = []
    monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: prompts.append(True) or ('save', False))
    assert manager.requestClose() and not prompts
    manager._quit_approved = False
    from test_workspace_persistence import draw_length
    draw_length(app.workspaceController.activeViewport)
    app.workspaceController.activeTab.historyController.capture()
    assert manager.dirty
    monkeypatch.setattr(manager, 'saveAs', lambda: pytest.fail('Existing workspace asked for a new path'))
    assert not manager.requestClose() and prompts == [True]
    wait_until(lambda: not manager.busy)
    from qt_dicom_viewer.core.workspace_document import read_document
    edits = read_document(target)['tabs'][0]['edits']['views']
    assert any(record.get('measurements') for record in edits.values())
    assert quits == [True] and not manager.dirty


@pytest.mark.parametrize('size', [(1000, 600), (1400, 900)])
def test_workspace_exit_settings_qml(scene, size, tmp_path):
    window, app, warnings = scene
    window.resize(*size)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('workspace')
    QTest.qWait(80)
    combo = find(window, 'workspaceExitBehavior')
    recovery = find(window, 'settingsWorkspaceAutomaticRecovery')
    assert combo.property('currentValue') == 'ask'
    for expected in ['save', 'discard']:
        combo.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Down)
        QTest.qWait(20)
        assert preference(app) == expected
        description = find(window, 'workspaceExitDescription')
        click(window, description)
        body = find(window, 'workspaceExitDescriptionText')
        assert body.property('text') == description.property('explanation')
        assert ('已有工作区直接保存' if expected == 'save' else '不保存') in body.property('text')
        assert body.property('paintedWidth') <= body.width() + 1
        assert body.property('paintedHeight') <= body.height() + 1
        QTest.keyClick(window, Qt.Key_Escape)
    assert window.grabWindow().save(str(tmp_path / 'exit-settings.png'))
    click(window, recovery)
    assert not app.workspaceDocumentController.automaticRecovery
    click(window, find(window, 'resetDisplaySettings'))
    assert preference(app) == 'ask' and combo.property('currentValue') == 'ask'
    assert app.workspaceDocumentController.automaticRecovery
    assert not warnings, warnings
