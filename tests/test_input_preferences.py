import pytest
from PySide6.QtGui import QKeySequence
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app


def test_input_privacy_scale_persist_and_validate(qt_app, tmp_path):
    path = tmp_path / 'settings.json'
    s = SettingsController(path=path)
    for group, key, value in [('input', 'reverseWheel', True), ('input', 'rightButton', 'pan'),
                              ('input', 'windowSensitivity', 1.5), ('input', 'zoomSensitivity', .5),
                              ('appearance', 'interfaceScale', 115), ('privacy', 'hideIdentity', True)]:
        assert s.setValue(group, key, value), (group, key)
        assert SettingsController(path=path).section(group)[key] == value
    assert not s.setValue('input', 'zoomSensitivity', 0)
    assert not s.setValue('appearance', 'interfaceScale', 500)
    assert not s.setValue('appearance', 'interfaceScale', 115.0)


def test_shortcut_conflicts_and_reserved(qt_app):
    from qt_dicom_viewer.settings.shortcuts import DEFAULT_BINDINGS, validate_bindings
    values = dict(DEFAULT_BINDINGS)
    values['pan'] = 'W'
    with pytest.raises(ValueError): validate_bindings(values)
    for bad in ['Ctrl+S', 'Ctrl+C', 'Ctrl+D', 'Alt+Tab', 'Escape', 'Ctrl+K, Ctrl+C', 'F11']:
        with pytest.raises(ValueError): validate_bindings(dict(values, pan=bad))
    valid = validate_bindings(dict(DEFAULT_BINDINGS, pan='Shift+P'))
    assert valid['pan'] == 'Shift+P'
    assert validate_bindings(dict(DEFAULT_BINDINGS, pan=''))['pan'] == ''


def test_scale_startup_is_bounded_and_preserves_os_factor(tmp_path):
    import json
    from qt_dicom_viewer.settings.interface_scale import apply_interface_scale
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'appearance':{'interfaceScale':130}}))
    env={'QT_SCALE_FACTOR':'1.25'}
    assert apply_interface_scale(path,env)==130
    assert float(env['QT_SCALE_FACTOR'])==1.625
    path.write_text(json.dumps({'appearance':{'interfaceScale':-1}}))
    env={}
    assert apply_interface_scale(path,env)==100
    assert 'QT_SCALE_FACTOR' not in env


def test_mouse_mapping_sensitivity_and_wheel_are_real(qt_app):
    from test_viewport_transform import _controller, _render_result
    from test_mouse_bindings import drag
    from dataclasses import replace
    c=_controller(); c.handleRenderResult(_render_result(c))
    s=c.settingsController
    try:
        before=c.viewport_state
        s.setValue('input','rightButton','pan')
        drag(c,2)
        assert c.panX != before.pan_x and c.zoom==before.zoom
        s.setValue('input','rightButton','none')
        before=c.viewport_state
        drag(c,2)
        assert c.viewport_state==before
        s.setValue('input','rightButton','zoom')
        s.setValue('input','zoomSensitivity',.5)
        drag(c,2); slow=c.zoom
        c._state=replace(c.viewport_state,zoom=before.zoom)
        s.setValue('input','zoomSensitivity',2)
        drag(c,2); assert c.zoom>slow
        baseline = c.viewport_state
        s.setValue('input','rightButton','window')
        s.setValue('input','windowSensitivity',.5)
        drag(c,2)
        slow = abs(c.current_window.width - baseline.window.width)
        c._state=baseline
        s.setValue('input','windowSensitivity',2)
        drag(c,2)
        assert abs(c.current_window.width-baseline.window.width)>slow
        c._state=replace(c.viewport_state,slice_index=1,slice_count=3)
        applied=[]
        c.apply_slice_index=lambda index: applied.append(index)
        c.handleWheel(120,0,0,0,0); assert applied[-1]==0
        s.setValue('input','reverseWheel',True)
        c.handleWheel(120,0,0,0,0); assert applied[-1]==2
    finally: c.shutdown()


def test_shortcut_binding_persists_after_reopen(qt_app, tmp_path):
    path = tmp_path/'settings.json'
    settings = SettingsController(path=path)
    values = dict(settings.section('shortcuts')['bindings'], pan='Shift+P')
    assert settings.setValue('shortcuts', 'bindings', values)
    assert SettingsController(path=path).section('shortcuts')['bindings']['pan'] == 'Shift+P'


def test_montage_identity_notifies_on_restored_display(qt_app):
    from test_montage_controller import _controller
    from dataclasses import replace
    from PySide6.QtTest import QSignalSpy
    c = _controller()
    try:
        assert c.patientName == 'Example Patient'
        assert 'P001' in c.patientSummary
        names = QSignalSpy(c._i18n_patientName)
        summaries = QSignalSpy(c._i18n_patientSummary)
        c._state = replace(c._state, display_settings=replace(c._state.display_settings, hide_sensitive_info=True))
        c.transformChanged.emit()  # workspace restoration's display notification
        assert names.count() == 1 and summaries.count() == 1
        assert c.patientName == c.patientSummary == '—'
    finally:
        c.shutdown()


def test_scale_does_not_compound_in_child_restart(tmp_path):
    import json
    from qt_dicom_viewer.settings.interface_scale import apply_interface_scale
    path = tmp_path/'settings.json'
    path.write_text(json.dumps({'appearance': {'interfaceScale': 130}}))
    env = {'QT_SCALE_FACTOR': '1.25'}
    apply_interface_scale(path, env)
    apply_interface_scale(path, env)  # updater/restart inherits the process environment
    assert float(env['QT_SCALE_FACTOR']) == 1.625
    path.write_text(json.dumps({'appearance': {'interfaceScale': 100}}))
    apply_interface_scale(path, env)
    assert float(env['QT_SCALE_FACTOR']) == 1.25
