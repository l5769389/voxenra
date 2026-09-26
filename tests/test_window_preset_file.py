import json
from copy import deepcopy
from pathlib import Path
import pytest
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.settings.window_presets import validate_document
from test_dicom_tags import qt_app


def write(path, entries):
    path.write_text(json.dumps(dict(schemaVersion=1, presets=entries)), encoding='utf-8')


def test_migrate_existing_presets_and_use_independent_file(tmp_path):
    settings_path = tmp_path / 'settings.json'
    custom = dict(presetId='custom-old', label='Existing', width=777, center=-222, enabled=False)
    settings_path.write_text(json.dumps(dict(window=dict(hidden=['ct-lung'], custom=[custom]))))
    settings = SettingsController(path=settings_path)
    path = Path(settings.windowPresetsPath)
    entries = json.loads(path.read_text())['presets']
    assert entries[-1] == custom
    assert not next(p for p in entries if p['presetId'] == 'ct-lung')['enabled']
    entries[0].update(width=123, center=12)
    entries.insert(0, dict(presetId='my-new-window', label='New', width=888, center=-333, enabled=True))
    write(path, entries)
    assert settings.reloadWindowPresets()
    assert settings.window_presets[0]['width'] == 888
    assert settings.window_presets[1]['width'] == 123
    assert settings.setValue('appearance', 'theme', 'light')
    assert 'window' not in json.loads(settings_path.read_text())
    restarted = SettingsController(path=settings_path)
    assert restarted.windowTemplates == settings.windowTemplates
    assert restarted.enableWindowTemplate('my-new-window', False)
    assert restarted.saveWindowTemplate('my-new-window', 'Renamed', 900, 20)
    assert not json.loads(path.read_text())['presets'][0]['enabled']
    assert json.loads(path.read_text())['presets'][0]['width'] == 900


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(schemaVersion=2),
    lambda d: d.update(presets=[dict(presetId='dup', label='x', width=10, center=0)] * 2),
    lambda d: d['presets'][0].update(width=0),
    lambda d: d['presets'][0].update(center=float('nan')),
    lambda d: d['presets'][0].update(enabled='false'),
    lambda d: d['presets'][0].update(label=123),
])
def test_invalid_file_keeps_last_valid_presets(tmp_path, mutation):
    settings = SettingsController(path=tmp_path / 'settings.json')
    path = Path(settings.windowPresetsPath)
    original = settings.windowTemplates
    data = json.loads(path.read_text())
    mutation(data)
    path.write_text(json.dumps(data))
    invalid = path.read_bytes()
    assert not settings.reloadWindowPresets()
    assert settings.windowTemplates == original and settings.message
    assert not settings.saveWindowTemplate('', 'New', 100, 0)
    assert path.read_bytes() == invalid


def test_external_edits_are_not_overwritten_and_failed_save_is_atomic(tmp_path, monkeypatch):
    settings = SettingsController(path=tmp_path / 'settings.json')
    path = Path(settings.windowPresetsPath)
    old = settings.windowTemplates
    entries = json.loads(path.read_text())['presets']
    entries[0]['width'] = 555
    write(path, entries)
    assert not settings.enableWindowTemplate('ct-brain', False)
    assert json.loads(path.read_text())['presets'][0]['width'] == 555
    assert settings.windowTemplates == old
    assert settings.reloadWindowPresets()
    old = settings.windowTemplates
    def fail(*args): raise OSError('read-only folder')
    monkeypatch.setattr('qt_dicom_viewer.settings.window_presets.write_document', fail)
    assert not settings.saveWindowTemplate('', 'New', 123, 0)
    assert settings.windowTemplates == old
    assert len(json.loads(path.read_text())['presets']) == 4


def test_empty_list_is_valid_and_malformed_startup_file_is_not_replaced(tmp_path):
    path = tmp_path / 'window-presets.json'
    path.write_text('{bad json')
    settings = SettingsController(path=tmp_path / 'settings.json')
    assert settings.message and settings.window_presets
    assert not settings.resetSection('window')
    assert path.read_text() == '{bad json'
    write(path, [])
    assert settings.reloadWindowPresets() and not settings.window_presets
    assert not SettingsController(path=tmp_path / 'settings.json').window_presets
    assert settings.resetSection('window')
    assert len(settings.window_presets) == 4


def test_open_location_and_reload_notifies_live_tools(qt_app, tmp_path, monkeypatch):
    from PySide6.QtCore import QObject
    from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
    host = QObject()
    host._settings_controller = SettingsController(host, path=tmp_path / 'settings.json')
    settings = host._settings_controller
    tools = ToolController(host)
    urls, signals = [], []
    tools.windowPresetsChanged.connect(lambda: signals.append(True))
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.settings_controller.QDesktopServices.openUrl', lambda url: urls.append(url.toLocalFile()) or True)
    assert settings.openWindowPresetsLocation()
    assert urls == [str(tmp_path)]
    write(Path(settings.windowPresetsPath), [dict(presetId='only', label='Only', width=999, center=33)])
    assert settings.reloadWindowPresets()
    assert signals and tools.windowPresets[0]['width'] == 999
    assert len(tools.windowPresets) == 1


def test_failed_first_migration_preserves_legacy_when_saving_other_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / 'settings.json'
    custom = dict(presetId='custom-old', label='Existing', width=777, center=-222, enabled=True)
    settings_path.write_text(json.dumps(dict(window=dict(hidden=['ct-lung'], custom=[custom]))))
    with monkeypatch.context() as patch:
        def fail(*args): raise OSError('write failed')
        patch.setattr('qt_dicom_viewer.settings.window_presets.write_document', fail)
        settings = SettingsController(path=settings_path)
        assert settings.message
        assert settings.setValue('appearance', 'theme', 'light')
    assert json.loads(settings_path.read_text())['window']['custom'] == [custom]
    restored = SettingsController(path=settings_path)
    assert restored.window_presets[-1]['label'] == 'Existing'
    assert Path(restored.windowPresetsPath).exists()
