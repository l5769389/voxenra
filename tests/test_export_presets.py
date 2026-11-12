"""Reusable presets contain preferences, never the current report's personal data."""
from copy import deepcopy
import json

import pytest
from test_dicom_tags import qt_app
from voxplane.ui.controller.settings_controller import SettingsController


def test_saving_named_preset_does_not_change_defaults_and_roundtrips(qt_app, tmp_path):
    path = tmp_path / 'settings.json'
    settings = SettingsController(path=path)
    defaults = settings.section('screenshot')
    options = dict(defaults, format='jpeg')
    assert settings.saveExportPreset('screenshot', 'Presentation', options)
    assert settings.section('screenshot') == defaults
    loaded = SettingsController(path=path)
    entry = loaded.section('exportPresets')['screenshot'][0]
    assert entry['name'] == 'Presentation' and entry['options']['format'] == 'jpeg'
    assert loaded.applyExportPreset('screenshot', entry['id'])
    assert loaded.section('screenshot')['format'] == 'jpeg'
    assert loaded.deleteExportPreset('screenshot', entry['id'])
    assert loaded.section('exportPresets')['screenshot'] == []
    assert loaded.section('screenshot')['format'] == 'jpeg'


def test_invalid_named_preset_is_atomic_and_rejects_personal_fields(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path/'settings.json')
    before = deepcopy(settings.values)
    for kind, name, options in [('report', '', {}), ('report', 'Notes', {'notes':'patient information'}),
                                 ('report','Study', {'patientName':'Someone'}),
                                 ('screenshot','Bad', {'format':'dicom'}), ('unknown','Bad',{})]:
        assert not settings.saveExportPreset(kind, name, options)
        assert settings.values == before
    assert settings.saveExportPreset('report','Basic',settings.section('report'))
    before = deepcopy(settings.values)
    assert not settings.saveExportPreset('report',' basic ',settings.section('report'))
    assert settings.values == before


def test_default_option_update_is_atomic_and_failed_write_keeps_state(qt_app, tmp_path, monkeypatch):
    settings = SettingsController(path=tmp_path/'settings.json')
    before = deepcopy(settings.values)
    assert not settings.setExportOptions('screenshot', {'format':'jpeg','longEdge':-1})
    assert settings.values == before
    monkeypatch.setattr(settings, '_persist_settings', lambda candidate: False)
    assert not settings.setExportOptions('screenshot', dict(settings.section('screenshot'),format='jpeg'))
    assert settings.values == before


def test_legacy_report_name_migrates_and_explicit_new_name_wins(qt_app, tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'export':{'reportSoftwareName':'Legacy Lab'}}))
    settings=SettingsController(path=path)
    assert settings.section('report')['softwareName']=='Legacy Lab'
    path.write_text(json.dumps({'export':{'reportSoftwareName':'Legacy Lab'},'report':{'softwareName':''}}))
    settings=SettingsController(path=path)
    assert settings.section('report')['softwareName']==''
    assert settings.setValue('export','reportSoftwareName','New Lab')
    assert settings.section('report')['softwareName']=='New Lab'


def test_compact_settings_navigation_migrates_only_old_default(tmp_path):
    from voxplane.settings.preferences import normalize_settings
    from voxplane.ui.controller.settings_controller import SettingsController
    import json
    assert normalize_settings({})['layout']['settingsNavigationWidth']==144
    assert normalize_settings({'schemaVersion':3,'layout':{'settingsNavigationWidth':180}})['layout']['settingsNavigationWidth']==144
    assert normalize_settings({'schemaVersion':3,'layout':{'settingsNavigationWidth':210}})['layout']['settingsNavigationWidth']==210
    path=tmp_path/'settings.json'
    settings=SettingsController(path=path)
    assert settings.setValue('layout','settingsNavigationWidth',132)
    assert settings.setValue('layout','settingsNavigationWidth',180)
    assert json.loads(path.read_text())['schemaVersion']==4
    assert SettingsController(path=path).section('layout')['settingsNavigationWidth']==180
