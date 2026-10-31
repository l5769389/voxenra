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
from test_tag_qml import find, click, descendants
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
    updater._version = "1.6.0"
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


@pytest.mark.parametrize('cached', [False, True])
def test_manual_update_failure_visible_with_retry_and_cached_timestamp(scene, tmp_path, cached):
    import json
    window, app, warnings = scene
    updater = app.updateController
    updater._cache = tmp_path / 'updates'
    updater._version = '1.6.0'
    updater._network = Network()
    if cached:
        updater._session_dismissed = '1.7.0'
        updater._check(False)
        updater._network.last.deliver(json.dumps(release_payload()).encode())
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('updates')
    QTest.qWait(60)
    check = find(window, 'settingsCheckUpdate')
    click(window, check)
    updater._network.last.code = 403
    updater._network.last.deliver(b'rate limit')
    QTest.qWait(30)
    status = find(window, 'settingsUpdateMessage')
    assert status.isVisible() and status.property('text') == str(message('updates.networkError'))
    assert updater.state == 'error' and check.isEnabled()
    cache_notice = next(item for item in descendants(window.contentItem())
                        if item.objectName() == 'settingsCachedUpdateMessage')
    assert cache_notice.isVisible() == cached
    if cached:
        assert '1.7.0' in cache_notice.property('text')
        assert updater._last_checked_at in cache_notice.property('text')
    assert window.grabWindow().save(str(tmp_path / 'manual-update-failure.png'))
    click(window, check)
    updater._network.last.deliver(json.dumps(release_payload('1.6.0')).encode())
    assert updater.state == 'current' and not cache_notice.isVisible()
    assert not warnings, warnings
