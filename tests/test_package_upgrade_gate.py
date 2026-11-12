"""Pinned upgrade baseline and packaged runtime evidence, without installing on the host."""
import json
from pathlib import Path

import pytest
from manual import verify_windows_package_updates as smoke

FIXTURES = Path(__file__).parent / 'fixtures' / 'upgrades'


def test_baseline_is_pinned_to_reviewed_250_packages():
    metadata, releases = smoke.load_baseline(FIXTURES / 'windows-baseline-v2.5.0.json', '2.6.0')
    assert metadata['tag_name'] == 'v2.5.0'
    assert releases['windows_installer'].digest == 'f94f753c896c5065303c6b05669d4278dfe49fb7150c42afbc210aff0451bc91'
    assert releases['windows_portable'].digest == '68aff3fc6fe64e2cf87c88568296a0f11eb1efc7b9a8e9b212d4f27d3e3af524'


@pytest.mark.parametrize('candidate', ['2.5.0', '2.4.0'])
def test_equal_or_newer_baseline_fails_instead_of_skipping(candidate):
    with pytest.raises(ValueError, match='older'):
        smoke.load_baseline(FIXTURES / 'windows-baseline-v2.5.0.json', candidate)


@pytest.mark.parametrize('change', ['digest', 'asset', 'draft'])
def test_invalid_baseline_is_rejected(tmp_path, change):
    payload = json.loads((FIXTURES / 'windows-baseline-v2.5.0.json').read_text())
    if change == 'digest':
        payload['assets'][0].pop('digest')
    elif change == 'asset':
        payload['assets'].pop(0)
    else:
        payload['draft'] = True
    path = tmp_path / 'baseline.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        smoke.load_baseline(path, '2.6.0')


def test_runtime_workspace_check_requires_version_and_actual_results(tmp_path, monkeypatch):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        expected = json.loads(Path(command[-2]).read_text())
        report = {key: value for key, value in expected.items() if key != 'sources'}
        report.update(passed=True, errors=[])
        Path(command[-1]).write_text(json.dumps(report))
    monkeypatch.setattr(smoke.subprocess, 'run', run)
    report = smoke.check_restored_workspace(tmp_path / 'VoxPlane.exe', FIXTURES / 'v2.5.0', tmp_path)
    assert report['passed'] is True
    assert commands[0][1] == '--verify-workspace'
    expected = json.loads(Path(commands[0][-2]).read_text())
    assert expected['settings']['appearance']['theme'] == 'graphite'
    assert expected['tabs'][0]['measurements'] and expected['tabs'][0]['qa']


@pytest.mark.parametrize('payload', [None, {'passed': False}, {'passed': True, 'version': '2.5.0'},
                                     {'passed': True, 'version': smoke.__version__, 'errors': []}])
def test_missing_failed_or_stale_packaged_report_fails(tmp_path, monkeypatch, payload):
    def run(command, **kwargs):
        if payload is not None:
            Path(command[-1]).write_text(json.dumps(payload))
    monkeypatch.setattr(smoke.subprocess, 'run', run)
    with pytest.raises((ValueError, FileNotFoundError)):
        smoke.check_restored_workspace(tmp_path / 'VoxPlane.exe', FIXTURES / 'v2.5.0', tmp_path)


def test_baseline_failure_writes_failed_gate_report_without_downloading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(smoke, 'require_clean_runner', lambda: None)
    def unexpected_download(*args, **kwargs):
        pytest.fail('invalid baseline must fail before invoking a package command')
    monkeypatch.setattr(smoke.subprocess, 'run', unexpected_download)
    with pytest.raises(FileNotFoundError):
        smoke.main(['--baseline', str(tmp_path / 'missing.json')])
    result = json.loads((tmp_path / 'build/test-results/installer/package-upgrade.json').read_text())
    assert result['status'] == 'failed' and result['error']
    assert result['packages'] == {}
    assert result['old_client_update_button'] == 'not_exercised'


def test_wrong_restored_results_fail_even_with_success_flag(tmp_path, monkeypatch):
    def run(command, **kwargs):
        expected = json.loads(Path(command[-2]).read_text())
        report = {key: value for key, value in expected.items() if key != 'sources'}
        report.update(passed=True, errors=[])
        report['tabs'][0]['qa']['water_ct_hu'] = 999
        Path(command[-1]).write_text(json.dumps(report))
    monkeypatch.setattr(smoke.subprocess, 'run', run)
    with pytest.raises(ValueError, match='workspace'):
        smoke.check_restored_workspace(tmp_path / 'VoxPlane.exe', FIXTURES / 'v2.5.0', tmp_path)
