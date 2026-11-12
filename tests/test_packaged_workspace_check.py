"""Installed-app diagnostic reads a real v2.5.0 save and live restored state."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from test_dicom_tags import qt_app

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/upgrades/v2.5.0'


def verifier():
    spec = importlib.util.spec_from_file_location('packaged_workspace_check', ROOT/'scripts/packaged_workspace_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_workspace


def inputs(tmp_path):
    folder = tmp_path/'fixture'
    shutil.copytree(FIXTURE, folder)
    settings = tmp_path/'config/display-settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'appearance': {'theme': 'graphite'}, 'updates': {'enabled': False}}))
    expected = json.loads((folder/'expected.json').read_text())
    expected['settings'] = {'appearance': {'theme': 'graphite'}, 'updates': {'enabled': False}}
    (folder/'expected.json').write_text(json.dumps(expected))
    return folder, settings


def test_restores_older_measurements_qa_cpr_and_loads_settings(qt_app, tmp_path):
    folder, settings = inputs(tmp_path)
    output = tmp_path/'report.json'
    assert verifier()(folder/'workspace.voxworkspace', folder/'expected.json', output, settings_path=settings) == 0
    report = json.loads(output.read_text())
    assert report['passed'] and not report['errors']
    assert report['settings']['appearance']['theme'] == 'graphite'
    assert report['settings']['updates']['enabled'] is False
    assert report['tabs'][0]['measurements'][0]['length_mm'] == 10
    assert report['tabs'][0]['qa']['water_ct_hu'] == 7
    assert report['tabs'][1]['ready'] is True


@pytest.mark.parametrize('failure', ['version', 'missing_image', 'measurement', 'qa', 'cpr', 'settings'])
def test_incomplete_or_mismatched_restore_fails(qt_app, tmp_path, failure):
    folder, settings = inputs(tmp_path)
    expected_path = folder/'expected.json'
    expected = json.loads(expected_path.read_text())
    if failure == 'version':
        expected['version'] = '0.0.0'
    elif failure == 'missing_image':
        (folder/'images/2.dcm').unlink()
    elif failure == 'measurement':
        expected['tabs'][0]['measurements'][0]['length_mm'] = 999
    elif failure == 'qa':
        expected['tabs'][0]['qa']['water_ct_hu'] = 999
    elif failure == 'cpr':
        expected['tabs'][1]['step_mm'] = 999
    else:
        expected['settings']['appearance']['theme'] = 'light'
    expected_path.write_text(json.dumps(expected))
    output = tmp_path/'report.json'
    assert verifier()(folder/'workspace.voxworkspace', expected_path, output, settings_path=settings) == 1
    report = json.loads(output.read_text())
    assert not report['passed'] and report['errors']
    field = {'version': 'version', 'missing_image': 'source image',
             'measurement': 'length_mm', 'qa': 'qa.water_ct_hu',
             'cpr': 'step_mm', 'settings': 'appearance.theme'}[failure]
    assert field in str(report['errors'])


@pytest.mark.parametrize('exit_code', [0, 1])
def test_frozen_entry_dispatches_workspace_check_and_preserves_exit(monkeypatch, exit_code):
    import runpy
    import sys
    from types import SimpleNamespace
    calls = []
    def verify(*args):
        calls.append(args)
        return exit_code
    monkeypatch.setitem(sys.modules, 'packaged_workspace_check', SimpleNamespace(verify_workspace=verify))
    monkeypatch.setattr(sys, 'argv', ['VoxPlane.exe', '--verify-workspace', 'old.voxworkspace', 'expected.json', 'report.json'])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(ROOT/'scripts/windows_entry.py'), run_name='__main__')
    assert error.value.code == exit_code
    assert calls == [('old.voxworkspace', 'expected.json', 'report.json')]
