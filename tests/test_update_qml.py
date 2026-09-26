"""Exercise the real themed update dialog and settings controls."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.app_updates import Installation, parse_release
from qt_dicom_viewer.i18n import message
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_app_updates import release_payload, Network, PAYLOAD, DIGEST
from test_pacs_qml import scene
from test_tag_qml import find, click
from test_dicom_tags import qt_app, wait_until


@pytest.mark.parametrize('theme,locale', [('dark', 'zh-CN'), ('light', 'en-US')])
def test_update_settings_badge_dialog_and_cancellation(scene, tmp_path, theme, locale):
    window, app, warnings = scene
    updater = app.updateController
    updater._cache = tmp_path / 'updates'
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    app.workspaceController.openSettings()
    QTest.qWait(60)
    click(window, find(window, 'settingsCategory-updates'))
    control = find(window, 'settingsAutomaticUpdates')
    assert control.property('checked')
    click(window, control)
    assert not SettingsController(path=app.settingsController._path).section('updates')['enabled']
    target = tmp_path / 'Voxenra.app'
    target.mkdir()
    updater._installation = Installation('macos', target)
    updater._release = parse_release(release_payload(), '1.6.0', 'macos')
    updater._set_state('available', message('updates.available', version='1.7.0'))
    QTest.qWait(40)
    badge = find(window, 'settingsUpdateBadge')
    assert badge.isVisible()
    version = find(window, 'settingsApplicationVersion')
    assert badge.mapToScene(QPointF()).x() >= version.mapToScene(QPointF()).x() + version.width()
    click(window, badge)
    QTest.qWait(80)
    assert find(window, 'applicationReleaseNotes').property('text') == updater.releaseNotes
    for name in ['applicationUpdateCancel', 'applicationUpdateAction']:
        item = find(window, name)
        corner = item.mapToScene(QPointF(item.width(), item.height()))
        assert corner.x() <= window.width() and corner.y() <= window.height()
    directory = Path('build/update-preview')
    directory.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(directory / f'update-{theme}.png'))
    click(window, find(window, 'applicationUpdateCancel'))
    QTest.qWait(60)
    assert app.settingsController.section('updates')['dismissedVersion'] == '1.7.0'
    assert badge.isVisible() and updater.hasUpdate
    assert window.grabWindow().save(str(directory / f'settings-{theme}.png'))
    assert not warnings, warnings


def test_workspace_cancel_prevents_installer_handoff(scene, tmp_path, monkeypatch):
    """A real Qt Quit event must pass through the existing workspace guard."""
    import json
    from PySide6.QtCore import QCoreApplication, QEvent
    window, app, warnings = scene
    updater = app.updateController
    target = tmp_path / 'Voxenra.app'
    target.mkdir()
    updater._installation = Installation('macos', target)
    updater._cache = tmp_path / 'updates'
    updater._network = Network()
    calls = []
    monkeypatch.setattr(app.workspaceDocumentController, 'requestClose', lambda: calls.append('cancel') or False)
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.update_controller.launch_installer', lambda *args: calls.append('installed'))
    # Deliver a real Quit event to QApplication; the fixture's test event loop
    # does not run QApplication.exec(), so explicitly dispatch the same event.
    updater.exitRequested.disconnect()
    updater.exitRequested.connect(lambda: QCoreApplication.sendEvent(QCoreApplication.instance(), QEvent(QEvent.Quit)))
    updater.check()
    updater._network.last.deliver(json.dumps(release_payload()).encode())
    updater.install()
    updater._network.last.deliver(f'{DIGEST}  {updater._release.name}'.encode())
    updater._network.last.deliver(PAYLOAD)
    assert calls == ['cancel'] and updater.state == 'ready'
    assert window.isVisible()
    updater.dismiss()
    assert updater._command is None
    assert not warnings, warnings
