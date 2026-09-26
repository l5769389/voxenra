from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pytest
from PySide6.QtCore import QSize

from qt_dicom_viewer.core.color_maps import apply_color_map, color_lut, COLOR_MAPS
from qt_dicom_viewer.settings.preferences import DEFAULTS, normalize_settings
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.controller.viewport.image_2d.mpr_viewport_controller import MprViewportController
from qt_dicom_viewer.model import MprPlane
from test_viewport_transform import _controller, _render_result


def test_settings_persist_validate_and_restore_one_section(tmp_path):
    path = tmp_path / 'display.json'
    settings = SettingsController(path=path)
    assert settings.setValue('scale', 'enabled', False)
    assert settings.setValue('corners', 'color', '#12ABef')
    assert settings.setValue('roi', 'mean', False)
    before = path.read_bytes()
    for section, key, value in [('scale', 'color', 'red'), ('corners', 'fontSize', 0),
                                ('measurement', 'lineWidth', float('nan')), ('roi', 'mean', 'false'),
                                ('colormap', 'gray', 'missing')]:
        assert not settings.setValue(section, key, value)
        assert path.read_bytes() == before
    loaded = SettingsController(path=path)
    assert loaded.values == settings.values
    assert loaded.resetSection('scale')
    assert loaded.values['scale'] == DEFAULTS['scale']
    assert loaded.values['corners']['color'] == '#12abef'
    assert not loaded.values['roi']['mean']
    values = loaded.values
    values['scale']['enabled'] = False
    assert loaded.values['scale']['enabled']  # QML gets a snapshot, not mutable backing state.


def test_malformed_settings_recover_and_save_failure_keeps_current_state(tmp_path):
    path = tmp_path / 'display.json'
    path.write_text('{broken')
    settings = SettingsController(path=path)
    assert settings.values == DEFAULTS and settings.message
    raw = deepcopy(DEFAULTS)
    raw['scale']['color'] = 'bad'
    raw['roi']['mean'] = False
    assert normalize_settings(raw)['roi']['mean'] is False
    assert normalize_settings(raw)['scale'] == DEFAULTS['scale']
    directory = tmp_path / 'directory'
    directory.mkdir()
    settings = SettingsController(path=directory)
    assert not settings.setValue('scale', 'enabled', False)
    assert settings.values['scale']['enabled']


def test_window_templates_crud_validation_and_enabled_list(tmp_path):
    settings = SettingsController(path=tmp_path / 'display.json')
    assert settings.saveWindowTemplate('', 'Custom Lung', 1200, -500)
    custom = settings.values['window']['custom'][0]
    assert not settings.saveWindowTemplate('', 'custom lung', 100, 0)
    assert not settings.saveWindowTemplate('', 'Invalid', 0, 0)
    assert settings.enableWindowTemplate('ct-lung', False)
    assert settings.enableWindowTemplate(custom['presetId'], False)
    assert settings.saveWindowTemplate(custom['presetId'], 'Updated', 900, -400)
    assert all(p['presetId'] not in ('ct-lung', custom['presetId']) for p in settings.window_presets)
    assert settings.enableWindowTemplate(custom['presetId'], True)
    assert settings.window_presets[-1]['width'] == 900
    assert SettingsController(path=tmp_path / 'display.json').window_presets == settings.window_presets
    assert settings.deleteWindowTemplate(custom['presetId'])
    assert not settings.values['window']['custom']


def test_corner_fields_reorder_remove_and_capacity():
    settings = SettingsController(path=False)
    assert settings.addCornerField('topRight', 'zoom')
    assert settings.moveCornerField('topRight', 2, -1)
    assert settings.values['corners']['topRight'] == ['patientName', 'zoom', 'patientId']
    assert settings.removeCornerField('topRight', 0)
    assert not settings.addCornerField('topRight', 'zoom')
    assert not settings.setValue('corners', 'topLeft', ['missing'])
    for field in ('manufacturer', 'modality', 'window', 'cursor', 'matrix', 'spacing'):
        assert settings.addCornerField('topRight', field)
    assert not settings.addCornerField('topRight', 'slice')


@pytest.mark.parametrize('name', COLOR_MAPS)
def test_lut_display_pixels_leave_source_data_unchanged(name):
    source = np.arange(256, dtype=np.uint8).reshape(16, 16)
    original = source.copy()
    colored = apply_color_map(source, name)
    np.testing.assert_array_equal(source, original)
    if name == 'grayscale':
        assert colored is source
    else:
        assert colored.shape == (16, 16, 3)
        np.testing.assert_array_equal(colored[0, 0], color_lut(name)[0])
        np.testing.assert_array_equal(colored[-1, -1], color_lut(name)[255])
    provider = DicomImageProvider()
    provider.set_array('lut', colored)
    image = provider.requestImage('lut/1', QSize(), QSize())
    assert image.width() == 16 and image.height() == 16
    if name == 'bwInverse':
        assert image.pixelColor(0, 0).red() == 255
        assert image.pixelColor(15, 15).red() == 0
    if name == 'hotIron':
        assert image.pixelColor(8, 8).red() > image.pixelColor(8, 8).blue()


def test_settings_reach_open_viewports_and_render_requests():
    controller = _controller()
    controller.handleRenderResult(_render_result(controller))
    settings = controller.settingsController
    requests = []
    controller.renderRequested.connect(requests.append)
    assert settings.setValue('colormap', 'gray', 'bwInverse')
    assert controller.colorMap == 'bwInverse' and controller.canvasBackgroundColor == '#ffffff'
    assert requests[-1].color_map == 'bwInverse'
    original_pixels = controller._modality_pixel.copy()
    settings.setValue('roi', 'mean', False)
    np.testing.assert_array_equal(controller._modality_pixel, original_pixels)
    config = replace(controller.viewport_config, viewport_id='mpr', viewport_type=MprPlane.CORONAL)
    mpr = MprViewportController(config, controller._tool_controller)
    settings.setValue('crosshair', 'axialColor', '#123456')
    settings.setValue('crosshair', 'axialWidth', 4.5)
    assert mpr.crosshairStyle['horizontalColor'] == '#123456'
    assert mpr.crosshairStyle['horizontalWidth'] == 4.5
    assert mpr._build_render_request(initial=True).color_map == 'bwInverse'
    controller.shutdown()


def test_palette_changes_while_first_frame_pending_request_latest_color():
    controller = _controller()
    requests = []
    controller.renderRequested.connect(requests.append)
    assert controller._frame_meta is None
    controller.settingsController.setValue('colormap', 'gray', 'pet')
    assert requests[-1].color_map == 'pet'
    assert requests[-1].window is None
    controller.shutdown()


def test_arrow_and_measurement_resets_are_separate():
    from qt_dicom_viewer.model import MeasurementKind
    from qt_dicom_viewer.ui.controller.viewport.controller.measure.measure_controller import MeasurementController
    from test_measurement_controller import _context, _position, _drag
    controller = MeasurementController()
    for kind, y in [(MeasurementKind.LENGTH, 10), (MeasurementKind.ARROW, 30)]:
        start, end = _position(0, y), _position(10, y)
        controller.begin(start, replace(_context(), measurement_kind=kind))
        controller.update(_drag(start, end))
        controller.end(end)
    assert {item['type'] for item in controller.measurementItems} == {'length', 'arrow'}
    controller.clear_kind(arrows=False)
    assert [item['type'] for item in controller.measurementItems] == ['arrow']
    controller.clear_kind(arrows=True)
    assert controller.measurementItems == []


def test_every_preference_survives_process_restart(tmp_path):
    """Write non-default values, then load through application startup in another process."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    expected = {
        'appearance': {'theme': 'light', 'language': 'en-US'},
        'updates': {'enabled': False, 'dismissedVersion': '1.7.0'},
        'workspace': {'automaticRecovery': False, 'exitBehavior': 'save'},
        'layout': {'rightPanelCollapsed': True, 'rightPanelWidth': 310,
                   'settingsNavigationWidth': 210, 'manualNavigationWidth': 320, 'rememberedMprLayout': 'quad',
                   'rememberedFourDLayout': 'rows', 'settingsCollapsedGroups': ['measurement-cards', 'appearance-theme']},
        'export': {'directory': str(tmp_path)},
        'colormap': {'gray': 'bwInverse', 'pet': 'hotIron'},
        'window': {'hidden': ['ct-lung'], 'custom': [dict(presetId='custom-restart', label='Restart',
                                                       width=900.0, center=-400.0, enabled=False)]},
        'crosshair': {'axialColor': '#123456', 'coronalColor': '#234567', 'sagittalColor': '#345678',
                      'axialWidth': 2.0, 'coronalWidth': 3.0, 'sagittalWidth': 4.0},
        'corners': {'enabled': False, 'fontSize': 17, 'lineHeight': 1.5, 'colorMode': 'custom',
                    'color': '#123456', 'topLeft': ['zoom'], 'topRight': ['matrix'],
                    'bottomLeft': ['spacing'], 'bottomRight': ['slice']},
        'scale': {'enabled': False, 'color': '#abcdef', 'lengthMm': 50},
        'measurement': {'editingColor': '#123456', 'completedColor': '#abcdef', 'lineWidth': 2.5,
                        'editingDash': False, 'completedDash': True, 'fontSize': 18,
                        'linkLabelToShape': True, 'cardTransparency': 60, 'decimalPlaces': 3,
                        'annotationColor': '#234567', 'annotationSize': 20},
        'services': {'mtfFrequencyUnit': 'lp/cm', 'mtfGaussianEquivalent': False, 'rampThicknessAngle': 45},
        'roi': {key: False for key in DEFAULTS['roi']},
    }
    assert expected.keys() == DEFAULTS.keys()
    path = tmp_path / 'restart-settings.json'
    settings = SettingsController(path=path)
    for section, values in expected.items():
        assert values.keys() == DEFAULTS[section].keys()
        for key, value in values.items():
            assert value != DEFAULTS[section][key], (section, key)
            assert settings.setValue(section, key, value), (section, key, settings.message)
    # A separate interpreter has no controller, QML, or module-level state to reuse.
    env = dict(os.environ)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
    script = '''import json, sys
from PySide6.QtCore import QCoreApplication
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
app = QCoreApplication([])
settings = SettingsController(path=sys.argv[1])
print(json.dumps(settings.values))
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], env=env,
                            text=True, capture_output=True, check=True, timeout=30)
    assert json.loads(result.stdout) == expected


def test_collapsed_settings_groups_validate_and_normalize():
    settings = SettingsController(path=False)
    assert settings.setValue('layout', 'settingsCollapsedGroups', ['measurement-cards', 'measurement-cards'])
    assert settings.values['layout']['settingsCollapsedGroups'] == ['measurement-cards']
    for value in ('measurement-cards', [None], [''], ['x' * 81], ['x'] * 129):
        assert not settings.setValue('layout', 'settingsCollapsedGroups', value)
        assert settings.values['layout']['settingsCollapsedGroups'] == ['measurement-cards']


def test_mtf_gaussian_equivalent_defaults_migration_and_restart(tmp_path):
    path = tmp_path/'display.json'
    # Existing preferences lacking the new field receive the requested default.
    path.write_text(json.dumps({'measurement': {'mtfFrequencyUnit': 'lp/cm'}}))
    settings = SettingsController(path=path)
    assert settings.section('services')['mtfGaussianEquivalent'] is True
    assert settings.section('services')['mtfFrequencyUnit'] == 'lp/cm'
    assert settings.setValue('services', 'mtfGaussianEquivalent', False)
    reloaded = SettingsController(path=path)
    assert reloaded.section('services')['mtfGaussianEquivalent'] is False
    assert not reloaded.setValue('services', 'mtfGaussianEquivalent', 'false')
    assert reloaded.resetSection('services')
    assert SettingsController(path=path).section('services')['mtfGaussianEquivalent'] is True


def test_service_settings_migrate_legacy_values_and_reset_independently(tmp_path):
    path = tmp_path/'legacy-service-settings.json'
    legacy = {'measurement': {'fontSize': 18, 'decimalPlaces': 3,
                              'mtfGaussianEquivalent': False, 'mtfFrequencyUnit': 'lp/cm',
                              'rampThicknessAngle': 45},
              'layout': {'settingsCollapsedGroups': ['measurement-mtf', 'measurement-thickness',
                                                    'measurement-cards']}}
    path.write_text(json.dumps(legacy))
    settings = SettingsController(path=path)
    calculations = {'mtfGaussianEquivalent': False, 'mtfFrequencyUnit': 'lp/cm', 'rampThicknessAngle': 45}
    assert settings.section('services') == calculations
    assert not set(calculations).intersection(settings.section('measurement'))
    assert settings.section('layout')['settingsCollapsedGroups'] == [
        'services-mtf', 'services-fwhm', 'measurement-cards']
    assert settings.resetSection('measurement')
    assert settings.section('services') == calculations
    assert SettingsController(path=path).section('services') == calculations
    settings.setValue('measurement', 'fontSize', 19)
    appearance = settings.section('measurement')
    assert settings.resetSection('services')
    reloaded = SettingsController(path=path)
    assert reloaded.section('measurement') == appearance
    assert reloaded.section('services') == DEFAULTS['services']
    saved = json.loads(path.read_text())
    assert not set(calculations).intersection(saved['measurement'])


def test_new_service_settings_take_precedence_without_mutating_input():
    from copy import deepcopy
    raw = {'measurement': {'mtfGaussianEquivalent': False, 'mtfFrequencyUnit': 'lp/cm',
                            'rampThicknessAngle': 45},
           'services': {'mtfGaussianEquivalent': True, 'mtfFrequencyUnit': 'lp/mm'}}
    original = deepcopy(raw)
    assert normalize_settings(raw)['services'] == {
        'mtfGaussianEquivalent': True, 'mtfFrequencyUnit': 'lp/mm', 'rampThicknessAngle': 45}
    assert raw == original
    raw['services']['mtfFrequencyUnit'] = 'invalid'
    assert normalize_settings(raw)['services']['mtfFrequencyUnit'] == 'lp/mm'
