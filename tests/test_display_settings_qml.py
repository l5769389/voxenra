from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_pacs_qml import scene
from test_tag_qml import find, click, type_text, descendants
from test_dicom_tags import qt_app, make_dicom, wait_until
from test_measurement_qml import viewport, _mouse_drag, _scene, _visual_children

def shot(window, name, directory):
    QTest.qWait(70)
    assert window.grabWindow().save(str(directory / (name + '.png')))


@pytest.mark.parametrize('category', ['colormap', 'window', 'crosshair', 'corners', 'scale', 'measurement', 'roi', 'export'])
def test_settings_pages_load_resize_and_reset(scene, category, tmp_path):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    QTest.qWait(50)
    click(window, find(window, 'settingsCategory-' + category))
    QTest.qWait(70)
    shot(window, category, tmp_path)
    window.resize(1280, 720)
    QTest.qWait(70)
    reset = find(window, 'resetDisplaySettings')
    top = reset.mapToScene(QPointF(0, 0))
    bottom = reset.mapToScene(QPointF(reset.width(), reset.height()))
    assert 0 <= top.x() < bottom.x() <= window.width() and 0 <= top.y() < bottom.y() <= window.height()
    click(window, reset)
    shot(window, category + '-minimum', tmp_path)
    assert not warnings, warnings


def test_real_settings_edits_and_reload(scene, tmp_path):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    QTest.qWait(50)
    click(window, find(window, 'settingsCategory-scale'))
    click(window, find(window, 'setting-scale-enabled'))
    type_text(window, find(window, 'setting-scale-color'), '#aabbcc')
    QTest.keyClick(window, Qt.Key_Tab)
    assert app.settingsController.values['scale'] == {'enabled': False, 'color': '#aabbcc', 'lengthMm': 100}
    click(window, find(window, 'settingsCategory-roi'))
    click(window, find(window, 'setting-roi-mean'))
    assert not app.settingsController.values['roi']['mean']
    click(window, find(window, 'settingsCategory-window'))
    from test_settings_redesign import reveal_setting
    reveal_setting(window, find(window, 'windowTemplateName'))
    type_text(window, find(window, 'windowTemplateName'), 'My Lung')
    type_text(window, find(window, 'windowTemplateWidth'), '1234')
    type_text(window, find(window, 'windowTemplateCenter'), '-456')
    reveal_setting(window, find(window, 'saveWindowTemplate'))
    click(window, find(window, 'saveWindowTemplate'))
    assert app.settingsController.values['window']['custom'][0]['width'] == 1234
    assert SettingsController(path=tmp_path / 'display-settings.json').values == app.settingsController.values
    assert not warnings, warnings


def test_real_image_color_map_window_templates_and_mpr(scene, tmp_path):
    window, app, warnings = scene
    instances = []
    for i in range(1, 9):
        path = tmp_path / f'volume-{i}.dcm'
        ds = make_dicom(path, i)
        del ds.NumberOfFrames
        ds.PatientID = 'SETTINGS-DEMO'
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, i * 1.5]
        ds.SliceThickness = 1.5
        ds.FrameOfReferenceUID = '1.2.826.0.1.3680043.10.999.101'
        ds.PixelData = (np.arange(4096).reshape(64, 64) // 4).astype(np.uint16).tobytes()
        ds.save_as(path, enforce_file_format=True)
        instances.append(_read_instance(path))
    series = _build_series_record(instances)
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 8, 8, 0, [series]))
    workspace = app.workspaceController
    wait_until(lambda: workspace.activeViewport is not None and bool(workspace.activeViewport.imageSource))
    viewport = workspace.activeViewport
    previous_revision = viewport._image_revision
    app.workspaceController.openSettings()
    QTest.qWait(50)
    click(window, find(window, 'settingsCategory-colormap'))
    button = find(window, 'colorMap-gray-hotIron')
    click(window, button)
    click(window, button)
    assert button.property('checked')
    wait_until(lambda: viewport._image_revision > previous_revision)
    image = app._image_provider._images[viewport.viewportId]
    assert any(image.pixelColor(x, 60).red() != image.pixelColor(x, 60).blue() for x in range(64))
    app.settingsController.saveWindowTemplate('', 'Custom', 1234, -456)
    assert viewport._tool_controller.windowPresets[-1]['width'] == 1234
    viewport.applyWindowPreset(-456, 1234)
    wait_until(lambda: viewport.current_window.width == 1234)
    click(window, find(window, 'openView-mpr'))
    wait_until(lambda: len(workspace.currentTabAllViewports) == 3 and all(v.imageSource for v in workspace.currentTabAllViewports), 15000)
    assert all(v.colorMap == 'hotIron' for v in workspace.currentTabAllViewports)
    app.settingsController.setValue('crosshair', 'axialColor', '#a855f7')
    app.settingsController.setValue('crosshair', 'axialWidth', 4)
    assert workspace.currentTabAllViewports[1].crosshairStyle['horizontalWidth'] == 4
    # Decoded frames can be ready before the asynchronous QML page is mounted.
    def visible_layers():
        return [i for i in descendants(window.contentItem())
                if i.objectName() == 'mprCrosshairLayer' and i.isVisible()]
    wait_until(lambda: len(visible_layers()) == 3)
    layers = visible_layers()
    assert len(layers) == 3
    assert sum(i.property('horizontalWidth') == 4 for i in layers) == 2
    assert sum(i.property('horizontalColor').name() == '#a855f7' for i in layers) == 2
    shot(window, 'live-mpr', tmp_path)
    app.workspaceController.openSettings()
    QTest.qWait(50)
    assert find(window, 'settingsCategory-colormap').property('checked')
    assert not warnings, warnings


def test_roi_styles_scale_and_arrow_are_applied_to_actual_viewport(viewport, tmp_path):
    window, controller, pixels, warnings = viewport
    settings = controller.settingsController
    controller._tool_controller.selectInteraction('measure:rect')
    _mouse_drag(window, _scene(pixels, 30, 35), _scene(pixels, 95, 95))
    original = controller.measurementController.measurementItems[0]['metrics'].copy()
    settings.setValue('roi', 'mean', False)
    settings.setValue('measurement', 'completedColor', '#ff0000')
    settings.setValue('measurement', 'lineWidth', 4)
    QTest.qWait(40)
    card = next(i for i in _visual_children(window.rootObject()) if i.objectName() == 'roiMetricCard' and i.isVisible())
    assert all(row['key'] != 'mean' for row in card.property('rows').toVariant())
    assert controller.measurementController.measurementItems[0]['metrics'] == original
    scale = next(i for i in _visual_children(window.rootObject()) if i.objectName() == 'imageScaleBar')
    assert scale.isVisible()
    mm = scale.property('lengthMm')
    assert scale.property('barPixels') / mm == pytest.approx(720 / 256)
    controller.apply_zoom(2)
    QTest.qWait(40)
    assert scale.property('barPixels') / scale.property('lengthMm') == pytest.approx(2 * 720 / 256)
    settings.setValue('scale', 'enabled', False)
    assert not scale.isVisible()
    settings.setValue('corners', 'topRight', ['zoom'])
    QTest.qWait(30)
    assert find(window, 'overlay-topRight').property('text') == 'Zoom: 200%'
    controller._tool_controller.activateTool('annotate')
    _mouse_drag(window, _scene(pixels, 100, 100), _scene(pixels, 125, 125))
    arrows = [i for i in controller.measurementController.measurementItems if i['type'] == 'arrow']
    assert len(arrows) == 1 and not arrows[0]['label']
    settings.setValue('measurement', 'annotationColor', '#a855f7')
    _mouse_drag(window, _scene(pixels, 125, 125), _scene(pixels, 130, 110))
    assert controller.measurementController.measurementItems[-1]['points'][-1]['column'] == pytest.approx(130, abs=.5)
    shot(window, 'live-annotations', tmp_path)
    QTest.keyClick(window, Qt.Key_Delete)
    assert len(controller.measurementController.measurementItems) == 1
    assert not warnings, warnings


def test_pacs_configuration_entry_opens_sources_after_other_settings(scene):
    window, app, warnings = scene
    app.settingsController.selectCategory('roi')
    app.workspaceController.openPacs()
    QTest.qWait(40)
    click(window, find(window, 'pacsConfigureEmpty'))
    assert app.settingsController.activeCategory == 'sources'
    assert find(window, 'pacsAddProfile').isEnabled()
    assert not warnings, warnings


@pytest.mark.parametrize('theme,locale', [('graphite', 'zh-CN'), ('light', 'en-US')])
def test_window_preset_file_reload_and_location(scene, tmp_path, monkeypatch, theme, locale):
    import json
    window, app, warnings = scene
    window.resize(1280, 720)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    app.workspaceController.openSettings()
    click(window, find(window, 'settingsCategory-window'))
    QTest.qWait(80)
    path = Path(app.settingsController.windowPresetsPath)
    assert path.is_file()
    assert window.findChild(QObject, "windowPresetsPath") is None
    urls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.settings_controller.QDesktopServices.openUrl',
                        lambda url: urls.append(url.toLocalFile()) or True)
    click(window, find(window, 'openWindowPresetsLocation'))
    assert urls == [str(path.parent)]
    data = json.loads(path.read_text())
    data['presets'][0].update(width=321, center=54)
    path.write_text(json.dumps(data))
    click(window, find(window, 'reloadWindowPresets'))
    QTest.qWait(80)
    assert find(window, 'windowWW-ct-brain').property('text') == '321'
    assert find(window, 'windowWL-ct-brain').property('text') == '54'
    assert not app.settingsController.messageIsError
    destination = Path('build/window-presets-preview'); destination.mkdir(parents=True, exist_ok=True)
    shot(window, theme + '-' + locale, destination)
    old = app.settingsController.windowTemplates
    path.write_text('{broken')
    click(window, find(window, 'reloadWindowPresets'))
    assert app.settingsController.windowTemplates == old
    assert app.settingsController.messageIsError
    assert find(window, 'settingsError').property('text')
    assert not warnings, warnings


@pytest.mark.parametrize('theme,locale', [('graphite', 'zh-CN'), ('light', 'en-US')])
def test_added_presets_apply_from_scrollable_window_panel(scene, tmp_path, theme, locale):
    from test_series_sidebar import phantom_series
    window, app, warnings = scene
    window.resize(1280, 720)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    series = phantom_series(tmp_path, 1, 'SYNTHETIC', '1.2.3.1', '20260903')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None and bool(app.workspaceController.activeViewport.imageSource))
    view = app.workspaceController.activeViewport
    QTest.qWait(100)
    scroll = find(window, 'toolDetailFlickable')
    for identifier, width, center in [('ct-liver', 150, 30), ('ct-spine-bone', 1800, 400)]:
        item = find(window, 'windowPreset-' + identifier)
        point = item.mapToItem(scroll, QPointF(0, 0))
        maximum = max(0, scroll.property('contentHeight') - scroll.height())
        scroll.setProperty('contentY', min(maximum, max(0, scroll.property('contentY') + point.y() - scroll.height()/2)))
        QTest.qWait(70)
        click(window, item)
        wait_until(lambda: view.current_window.width == width and view.current_window.center == center)
        assert item.property('checked')
    destination = Path('build/window-presets-preview'); destination.mkdir(parents=True, exist_ok=True)
    shot(window, 'new-presets-' + theme + '-' + locale, destination)
    assert not warnings, warnings
