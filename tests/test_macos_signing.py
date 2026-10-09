"""Signing orchestration contracts; Apple tools are external and require paid credentials."""
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = 'Developer ID Application: Example (ABCDE12345)'
FINGERPRINT = 'A' * 40


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    return importlib.import_module('macos_signing')


def test_identity_requires_valid_developer_id_and_exact_match(signing, monkeypatch):
    output = f'  1) {FINGERPRINT} "{IDENTITY}"\n  2) {"B" * 40} "Apple Development: Example"\n  2 valid identities found\n'
    monkeypatch.setattr(signing.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, output, ''))
    assert signing.resolve_identity(IDENTITY) == FINGERPRINT
    assert signing.resolve_identity(FINGERPRINT.lower()) == FINGERPRINT
    for invalid in ['-', 'Example', 'Apple Development: Example', 'missing']:
        with pytest.raises(ValueError, match='Developer ID'):
            signing.resolve_identity(invalid)


@pytest.mark.parametrize('reply', ['{"id":"request-id","status":"Invalid"}',
                                  '{"id":"request-id","status":"In Progress"}',
                                  '{}', 'not-json'])
def test_unaccepted_notarization_never_staples(signing, monkeypatch, tmp_path, reply):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, reply, '')
    monkeypatch.setattr(signing.subprocess, 'run', run)
    with pytest.raises(ValueError):
        signing.notarize(tmp_path / 'app.zip', 'profile', tmp_path / 'logs', 'app')
    assert not any('stapler' in command for command in commands)
    assert (tmp_path / 'logs/app-submit.json').read_text() == reply


def test_notary_cli_failure_cannot_be_misreported_as_success(signing, monkeypatch, tmp_path):
    monkeypatch.setattr(signing.subprocess, 'run', lambda command, **kw:
                        subprocess.CompletedProcess(command, 1, '{"status":"Accepted"}', 'network failure'))
    with pytest.raises(subprocess.CalledProcessError):
        signing.notarize(tmp_path / 'app.zip', 'profile', tmp_path / 'logs', 'app')


def test_app_ticket_precedes_dmg_build_and_both_are_assessed(signing, monkeypatch, tmp_path):
    app = tmp_path / 'Voxenra.app'
    app.mkdir()
    events = []
    def run(command, **kwargs):
        events.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({'id': 'request-id', 'status': 'Accepted'}), '')
    monkeypatch.setattr(signing.subprocess, 'run', run)
    signing.notarize_app(app, 'profile', tmp_path / 'logs')
    output = tmp_path / 'Voxenra.dmg'
    output.write_bytes(b'dmg')
    signing.notarize_dmg(output, FINGERPRINT, 'profile', tmp_path / 'logs')
    app_staple = ['xcrun', 'stapler', 'staple', str(app)]
    assert app_staple in events
    assert ['xcrun', 'stapler', 'validate', str(app)] in events
    assert ['spctl', '--assess', '--type', 'execute', '--verbose=2', str(app)] in events
    assert events.index(app_staple) < next(i for i, cmd in enumerate(events) if cmd[0] == 'codesign' and str(output) in cmd)
    assert ['xcrun', 'stapler', 'validate', str(output)] in events
    assert ['spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', str(output)] in events


def test_release_missing_credentials_stops_before_build(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    mac = importlib.import_module('build_macos')
    monkeypatch.delenv('MACOS_SIGN_IDENTITY', raising=False)
    monkeypatch.delenv('MACOS_NOTARY_PROFILE', raising=False)
    monkeypatch.setattr(mac.sys, 'platform', 'darwin')
    monkeypatch.setattr(mac.sys, 'version_info', (3, 13))
    monkeypatch.setattr(mac.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(mac, 'prepare_assets', lambda *a: pytest.fail('must not build without credentials'))
    with pytest.raises(SystemExit) as error:
        mac.main(['--release'])
    assert error.value.code == 2
    assert '正式签名检查需要' in capsys.readouterr().err


def test_check_only_authenticates_without_build_or_upload(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    mac = importlib.import_module('build_macos')
    monkeypatch.setattr(mac.sys, 'platform', 'darwin')
    monkeypatch.setattr(mac.platform, 'machine', lambda: 'arm64')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[0] == 'security':
            return subprocess.CompletedProcess(command, 0, f'1) {FINGERPRINT} "{IDENTITY}"\n', '')
        assert command[:2] == ['xcrun', '--find'] or command[:3] == ['xcrun', 'notarytool', 'history']
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(mac.subprocess, 'run', run)
    monkeypatch.setattr(mac, 'prepare_assets', lambda *a: pytest.fail('check-only must not build'))
    assert mac.main(['--check-signing', '--sign-identity', IDENTITY, '--notary-profile', 'profile']) == 0
    assert ['xcrun', 'notarytool', 'history', '--keychain-profile', 'profile', '--output-format', 'json'] in commands


@pytest.mark.parametrize('accepted', [False, True])
def test_dmg_replaced_only_after_successful_notarization(monkeypatch, tmp_path, accepted):
    import plistlib
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    mac = importlib.import_module('build_macos')
    monkeypatch.setattr(mac, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(mac, 'app_version', lambda _: '1.0.0')
    monkeypatch.setattr(mac.sys, 'platform', 'darwin')
    monkeypatch.setattr(mac.sys, 'version_info', (3, 13))
    monkeypatch.setattr(mac.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(mac, 'prepare_assets', lambda _: tmp_path / 'assets')
    for relative in ['src/qt_dicom_viewer/qml/Main.qml', 'scripts/windows_entry.py']:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.touch()
    app = tmp_path / 'dist/macos/Voxenra.app'
    (app / 'Contents/MacOS').mkdir(parents=True)
    (app / 'Contents/Resources').mkdir()
    (app / 'Contents/MacOS/Voxenra').touch()
    (app / 'Contents/Resources/app.icns').touch()
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIconFile': 'app.icns'}))
    output = tmp_path / 'dist/installers/Voxenra-1.0.0-macos-arm64.dmg'
    output.parent.mkdir()
    output.write_bytes(b'previous successful artifact')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[0] == 'security':
            reply = f'1) {FINGERPRINT} "{IDENTITY}"\n'
        elif 'dmgbuild' in command:
            assert ['xcrun', 'stapler', 'validate', str(app)] in commands
            Path(command[-1]).write_bytes(b'new artifact')
            reply = ''
        else:
            status = 'Invalid' if not accepted and 'submit' in command and command[3].endswith('.dmg') else 'Accepted'
            reply = json.dumps({'id': 'request-id', 'status': status})
        return subprocess.CompletedProcess(command, 0, reply, '')
    monkeypatch.setattr(mac.subprocess, 'run', run)
    result = mac.main(['--release', '--sign-identity', IDENTITY, '--notary-profile', 'profile'])
    assert result == (0 if accepted else 1)
    assert output.read_bytes() == (b'new artifact' if accepted else b'previous successful artifact')
    assert not list(output.parent.glob('.macos-build-*'))
