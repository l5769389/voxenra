"""Update safety and state transitions; no real release is installed by these tests."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtNetwork import QNetworkReply

from qt_dicom_viewer.core.app_updates import (
    Installation, REPOSITORY, RELEASE_API, parse_release, parse_checksum, version_tuple, trusted_download_url,
)
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.update_controller import UpdateController
from test_dicom_tags import qt_app


PAYLOAD = b'a verified application package'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def release_payload(version='1.7.0', kind='macos'):
    suffix = {'macos': 'macos-arm64.dmg', 'windows_installer': 'windows-x64-setup.exe',
              'windows_portable': 'windows-x64-portable.exe'}[kind]
    name = f'Voxenra-{version}-{suffix}'
    base = f'https://github.com/{REPOSITORY}/releases/download/v{version}/'
    return dict(tag_name='v' + version, draft=False, prerelease=False, body='New features\n\n- Improved viewing.', assets=[
        dict(name=name, state='uploaded', size=len(PAYLOAD), browser_download_url=base + name, digest='sha256:' + DIGEST),
        dict(name=name + '.sha256', state='uploaded', size=100, browser_download_url=base + name + '.sha256'),
    ])


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()
    redirected = Signal(QUrl)

    def __init__(self, parent):
        super().__init__(parent)
        self.buffer = b''
        self.code = 200
        self.failure = QNetworkReply.NoError
        self.allowed = False
        self.aborted = False

    def setReadBufferSize(self, size): pass
    def bytesAvailable(self): return len(self.buffer)
    def read(self, size):
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result
    def attribute(self, key): return self.code
    def error(self): return self.failure
    def redirectAllowed(self): self.allowed = True
    def abort(self):
        self.aborted = True
        self.failure = QNetworkReply.OperationCanceledError
        self.finished.emit()
    def deliver(self, data, *, complete=True):
        self.buffer += data
        self.readyRead.emit()
        if complete and not self.aborted:
            self.finished.emit()


class Network(QObject):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.replies = []
    def get(self, request):
        self.requests.append(request.url().toString())
        reply = Reply(self)
        self.replies.append(reply)
        return reply
    @property
    def last(self): return self.replies[-1]


@pytest.fixture
def updater(qt_app, tmp_path):
    target = tmp_path / 'Voxenra.app'
    target.mkdir()
    settings = SettingsController(path=tmp_path / 'settings.json')
    network = Network()
    controller = UpdateController(settings, installation=Installation('macos', target), network=network,
                                  cache=tmp_path / 'updates', version='1.6.0')
    yield controller, settings, network
    controller.shutdown()
    from shiboken6 import delete
    delete(controller)
    delete(network)


def available(updater, manual=False):
    controller, _, network = updater
    controller._check(manual)
    network.last.deliver(json.dumps(release_payload()).encode())
    assert controller.state == 'available'


def download(updater):
    controller, _, network = updater
    available(updater)
    controller.install()
    network.last.deliver(f'{DIGEST}  {controller._release.name}\n'.encode())
    assert controller.state == 'downloading'


def test_numeric_versions_and_pre_releases():
    assert version_tuple('v1.10.0') > version_tuple('1.9.9')
    for value in ['1.7.0-beta', '../1.7.0', '1.7', '01.7.0', None]:
        with pytest.raises(ValueError): version_tuple(value)
    data = release_payload()
    assert parse_release(data, '1.7.0', 'macos') is None
    assert parse_release(data, '1.8.0', 'macos') is None
    for key in ['draft', 'prerelease']:
        assert parse_release(dict(data, **{key: True}), '1.6.0', 'macos') is None


@pytest.mark.parametrize('kind', ['macos', 'windows_installer', 'windows_portable'])
def test_release_platform_and_checksum(kind):
    release = parse_release(release_payload(kind=kind), '1.6.0', kind)
    assert release.digest == DIGEST
    assert parse_checksum(f'{DIGEST} *{release.name}\r\n'.encode(), release.name) == DIGEST
    assert parse_checksum(DIGEST.encode(), release.name) == DIGEST
    for content in [b'bad', f'{DIGEST} another.exe'.encode(), f'{DIGEST}\n{DIGEST}'.encode()]:
        with pytest.raises(ValueError): parse_checksum(content, release.name)


def test_reject_incomplete_malicious_or_unbounded_release():
    for mutate in [lambda d: d['assets'].pop(),
                   lambda d: d['assets'][0].update(state='new'),
                   lambda d: d['assets'][0].update(size=3 * 1024**3),
                   lambda d: d['assets'][0].update(size=True),
                   lambda d: d['assets'][0].update(digest='sha256:no'),
                   lambda d: d['assets'][0].update(browser_download_url='https://evil.example/app.exe'),
                   lambda d: d['assets'][0].update(browser_download_url=d['assets'][0]['browser_download_url'].replace('/v1.7.0/', '/v1.8.0/'))]:
        data = release_payload()
        mutate(data)
        with pytest.raises(ValueError): parse_release(data, '1.6.0', 'macos')
    for url in ['http://github.com/a', 'https://github.com.evil.example/a', 'https://user@github.com/a', 'file:///tmp/a']:
        assert not trusted_download_url(url, redirect=True)


def test_startup_setting_and_dismissal_survive_restart(updater):
    controller, settings, network = updater
    prompts = []
    controller.showDialog.connect(lambda: prompts.append(True))
    settings.setValue('updates', 'enabled', False)
    controller._startup_check()
    assert network.requests == []
    settings.setValue('updates', 'enabled', True)
    controller._startup_check()
    assert network.requests == [RELEASE_API]
    network.last.deliver(json.dumps(release_payload()).encode())
    assert len(prompts) == 1
    controller.dismiss()
    assert controller.hasUpdate
    reloaded = SettingsController(path=settings._path)
    assert reloaded.section('updates') == {'enabled': True, 'dismissedVersion': '1.7.0'}
    controller._settings = reloaded
    controller._startup_check()
    network.last.deliver(json.dumps(release_payload()).encode())
    assert len(prompts) == 1
    controller._startup_check()
    network.last.deliver(json.dumps(release_payload('1.8.0')).encode())
    assert len(prompts) == 2


def test_check_failures_are_silent_for_automatic_and_manual_checks(updater):
    controller, _, network = updater
    prompts = []
    controller.showDialog.connect(lambda: prompts.append(True))
    controller._startup_check()
    network.last.code = 403
    network.last.deliver(b'rate limit')
    assert controller.state == 'idle' and not prompts
    controller.check()
    network.last.code = 403
    network.last.deliver(b'rate limit')
    assert controller.state == 'idle' and not prompts
    controller.check()
    network.last.deliver(json.dumps(release_payload('1.6.0')).encode())
    assert controller.state == 'current' and not prompts
    controller.check()
    network.last.deliver(json.dumps(release_payload()).encode())
    assert controller.state == 'available' and len(prompts) == 1


def test_disabling_while_check_in_flight_suppresses_prompt(updater):
    controller, settings, network = updater
    prompts = []
    controller.showDialog.connect(lambda: prompts.append(True))
    controller._startup_check()
    settings.setValue('updates', 'enabled', False)
    network.last.deliver(json.dumps(release_payload()).encode())
    assert controller.hasUpdate and not prompts


def test_streamed_download_handoff_only_after_exit(updater, monkeypatch):
    controller, _, network = updater
    exits, launches = [], []
    controller.exitRequested.connect(lambda: exits.append(True))
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.update_controller.launch_installer', lambda *args: launches.append(args))
    download(updater)
    reply = network.last
    reply.deliver(PAYLOAD[:10], complete=False)
    assert 0 < controller.progress < 1 and not exits
    reply.deliver(PAYLOAD[10:])
    assert controller.state == 'ready' and len(exits) == 1 and not launches
    assert (controller._stage / controller._release.name).read_bytes() == PAYLOAD
    assert json.loads((controller._cache / 'pending.json').read_text())['version'] == '1.7.0'
    controller.shutdown()
    controller.install_after_exit()
    assert len(launches) == 1


@pytest.mark.parametrize('payload', [b'bad', PAYLOAD + b'excess', PAYLOAD[:-1] + b'X'])
def test_invalid_package_never_exits_or_installs(updater, payload):
    controller, _, network = updater
    exits = []
    controller.exitRequested.connect(lambda: exits.append(True))
    download(updater)
    network.last.deliver(payload)
    assert controller.state == 'error' and not exits and controller._command is None
    assert not (controller._stage / controller._release.name).exists()


def test_mismatched_manifest_checksum_blocks_download(updater):
    controller, _, network = updater
    available(updater)
    controller.install()
    network.last.deliver(('f' * 64).encode())
    assert controller.state == 'error'
    assert len(network.requests) == 2


@pytest.mark.parametrize('at_ready', [False, True])
def test_cancel_cleans_package_and_keeps_badge(updater, at_ready):
    controller, settings, network = updater
    download(updater)
    network.last.deliver(PAYLOAD if at_ready else PAYLOAD[:4], complete=at_ready)
    controller.dismiss()
    assert controller.hasUpdate and controller.state == 'available'
    assert settings.section('updates')['dismissedVersion'] == '1.7.0'
    assert controller._command is None
    assert not (controller._stage / controller._release.name).exists()
    # Late callbacks from cancelled replies cannot complete another request.
    old = network.last
    controller.check()
    old.finished.emit()
    assert controller.state == 'checking'


def test_redirect_and_timeout_are_bounded(updater):
    controller, _, network = updater
    download(updater)
    network.last.redirected.emit(QUrl('https://release-assets.githubusercontent.com/asset'))
    assert network.last.allowed
    network.last.redirected.emit(QUrl('http://evil.example/asset'))
    assert controller.state == 'error'
    controller.check()
    controller._timeout()
    assert controller.state == 'available'


def test_development_runtime_cannot_replace_python(qt_app, tmp_path):
    controller = UpdateController(SettingsController(path=False), installation=Installation('', None, 'updates.development'),
                                  cache=tmp_path, network=Network(), version="1.6.0")
    controller.check()
    controller._network.last.deliver(json.dumps(release_payload()).encode())
    assert controller.hasUpdate and not controller.canInstall
    controller.install()
    assert len(controller._network.requests) == 1
    controller.shutdown()
    from shiboken6 import delete
    delete(controller._network)
    delete(controller)


def test_last_install_failure_is_silent_and_log_remains_available(updater):
    controller, settings, network = updater
    settings.setValue('updates', 'enabled', False)
    stage = controller._cache / 'update-failed'
    stage.mkdir(parents=True)
    (stage / 'result').write_text('failed')
    (stage / 'install.log').write_text('test failure')
    (controller._cache / 'pending.json').write_text(json.dumps({'directory': stage.name, 'version': '1.7.0'}))
    prompts = []
    controller.showDialog.connect(lambda: prompts.append(True))
    controller._startup_check()
    assert controller.state == 'idle' and not prompts and controller.hasLog
    assert settings.section('updates')['dismissedVersion'] == '1.7.0'
    assert not network.requests


def test_cached_badge_survives_disabled_and_offline_restart(updater):
    controller, settings, network = updater
    available(updater)
    controller.dismiss()
    settings.setValue('updates', 'enabled', False)
    restarted = UpdateController(SettingsController(path=settings._path), installation=controller._installation,
                                 cache=controller._cache, network=Network(), version='1.6.0')
    assert restarted.hasUpdate and restarted.latestVersion == '1.7.0'
    restarted._startup_check()
    assert not restarted._network.requests
    restarted.check()
    restarted._network.last.code = 503
    restarted._network.last.deliver(b'unavailable')
    assert restarted.hasUpdate and restarted.state == 'available'
    restarted.shutdown()
    from shiboken6 import delete
    delete(restarted._network)
    delete(restarted)


def test_disk_full_and_file_write_failure_keep_running(updater, monkeypatch):
    controller, _, network = updater
    available(updater)
    import shutil
    real_usage = shutil.disk_usage
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: type('Usage', (), {'free': 1})())
    controller.install()
    assert controller.state == 'error' and len(network.requests) == 1
    monkeypatch.setattr(shutil, 'disk_usage', real_usage)
    controller.install()
    network.last.deliver(f'{DIGEST}  {controller._release.name}'.encode())
    controller._file.close()
    class FullDisk:
        def write(self, chunk): raise OSError('Disk full')
        def close(self): raise OSError('Flush failed')
    controller._file = FullDisk()
    exits = []
    controller.exitRequested.connect(lambda: exits.append(True))
    network.last.deliver(PAYLOAD)
    assert controller.state == 'error' and not exits and controller._command is None


def test_runtime_detection_never_confuses_installer_portable_or_source(tmp_path, monkeypatch):
    import qt_dicom_viewer.core.app_updates as module
    monkeypatch.setattr(module.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setattr(module.platform, 'machine', lambda: 'AMD64')
    exe = tmp_path / 'Voxenra.exe'
    exe.touch()
    monkeypatch.setattr(module.sys, 'executable', str(exe))
    assert module.detect_installation().kind == 'windows_portable'
    (tmp_path / '_internal').mkdir()
    assert not module.detect_installation().kind
    (tmp_path / 'unins000.exe').touch()
    assert module.detect_installation().kind == 'windows_installer'
    monkeypatch.setattr(module.sys, 'frozen', False)
    assert module.detect_installation().reason == 'updates.development'
