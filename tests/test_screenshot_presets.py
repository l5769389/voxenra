import pytest
from PySide6.QtGui import QImage

def test_screenshot_validation():
    from voxplane.settings.screenshot_presets import validate_options
    assert validate_options({})['anonymous'] is True
    for raw in ({'scope':'bad'}, {'longEdge':511}, {'longEdge':True}, {'jpegQuality':101}, {'filenamePrefix':'../x'}, {'patientName':'x'}):
        with pytest.raises(ValueError): validate_options(raw)

def test_screenshot_encoding_size_and_metadata(qt_app, tmp_path):
    from voxplane.ui.controller.export_controller import ExportController
    from types import SimpleNamespace
    controller = ExportController(SimpleNamespace(activeViewport=None), None)
    controller._screenshot_options = {'format':'jpeg', 'size':'longEdge', 'longEdge':512, 'jpegQuality':90, 'revealAfter':False}
    image = QImage(400,200,QImage.Format_RGB32); image.fill(0xffcc3322); image.setText('Patient','private')
    target=tmp_path/'capture.jpg'
    controller._save_png(image,target)
    saved=QImage(str(target))
    assert (saved.width(),saved.height()) == (512,256)
    assert saved.textKeys() == []
    assert target.read_bytes().startswith(b'\xff\xd8')
    controller.shutdown()

from test_dicom_tags import qt_app

def test_capture_tab_restores_layers_and_rejects_changed_source(sidebar_scene, monkeypatch, tmp_path):
    from PySide6.QtTest import QTest
    from test_dicom_tags import wait_until
    from test_tag_qml import find
    from voxplane.model import TabType
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Capture', TabType.TWO_D)
    wait_until(lambda: ws.activeLoadState.status == 'ready', timeout=15000)
    center = find(window, 'centerPanel')
    wait_until(lambda: center.property('exportItem') is not None)
    item = center.property('exportItem')
    target = tmp_path/'tab.jpg'
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName', lambda *args: (str(target),'JPEG'))
    original = item.property('captureParameters')
    app.exportController.exportScreenshot(item, item, dict(scope='tab',format='jpeg',size='longEdge',longEdge=512,anonymous=False,parameters=False,measurements=False))
    wait_until(lambda: not app.exportController.busy)
    assert not app.exportController.isError, app.exportController.message
    result = QImage(str(target))
    assert max(result.width(),result.height()) == 512
    assert item.property('captureParameters') == original
    assert not item.property('capturingPng')
    app.exportController.exportScreenshot(item,item,dict(anonymous=False))
    ws.activeViewport.setSliceIndex((ws.activeViewport.sliceIndex + 1) % ws.activeViewport.sliceCount)
    wait_until(lambda: not app.exportController.busy)
    assert app.exportController.isError
    assert item.property('captureParameters') == original
    assert not item.property('capturingPng')

from test_series_sidebar import sidebar_scene

def test_whole_mpr_tab_capture_has_tab_dimensions(sidebar_scene, monkeypatch, tmp_path):
    from test_dicom_tags import wait_until
    from test_tag_qml import find
    from voxplane.model import TabType
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'MPR capture', TabType.MPR)
    wait_until(lambda: ws.activeLoadState.status == 'ready', timeout=15000)
    center = find(window, 'centerPanel')
    wait_until(lambda: center.property('tabExportItem') is not None)
    item = center.property('tabExportItem')
    target = tmp_path/'tab.png'
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName', lambda *args: (str(target),'PNG'))
    app.exportController.exportScreenshot(center.property('exportItem'), item, dict(scope='tab',anonymous=False))
    wait_until(lambda: not app.exportController.busy)
    assert not app.exportController.isError, app.exportController.message
    image=QImage(str(target))
    assert image.width()/image.height() == pytest.approx(item.width()/item.height(), rel=.01)
    assert not warnings, warnings

def test_nested_capture_flags_restore_original_values(qt_app):
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtCore import QUrl
    from voxplane.ui.controller.export_controller import ExportController
    from types import SimpleNamespace
    engine=QQmlEngine(); component=QQmlComponent(engine)
    component.setData(b'import QtQuick; Item { id: root; property bool anonymousExport: false; property bool capturingPng: false; Item { objectName: "child"; property bool anonymousExport: root.anonymousExport; property bool capturingPng: root.capturingPng } }',QUrl())
    item=component.create()
    controller=ExportController(SimpleNamespace(activeViewport=None),None)
    controller._prepare_capture(item)
    assert item.property('capturingPng')
    assert item.childItems()[0].property('capturingPng')
    controller._restore_capture()
    assert not item.property('capturingPng')
    assert not item.childItems()[0].property('capturingPng')
    assert not item.childItems()[0].property('anonymousExport')
    controller.shutdown()
    item.deleteLater()


import os
from test_pacs_qml import scene
from test_pet_fusion import paired_series


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='Requires a native desktop OpenGL window')
def test_native_3d_whole_tab_composes_frame_and_restores_flags(scene, paired_series, tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from test_dicom_tags import wait_until
    from test_tag_qml import find
    from voxplane.model import DicomFolderScanSnapshot

    window, app, warnings = scene
    catalog, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    workspace = app.workspaceController
    wait_until(lambda: workspace.activeLoadState.status == 'ready', timeout=20000)
    QTest.qWait(100)
    workspace.createTab(ct.series_instance_uid, 'Native capture', '3d')
    wait_until(lambda: workspace.activeLoadState.status == 'ready', timeout=20000)
    assert workspace.activeTabType == '3d'
    view = workspace.activeViewport
    wait_until(lambda: view._host is not None and view._host.isVisible()
               and view._host.frame_ready and view._host.surface_ready(), timeout=20000)
    center = find(window, 'centerPanel')
    item = center.property('tabExportItem')
    container = find(window, 'volumeWindowContainer')
    frame = find(window, 'volumeViewportFrame')
    QTest.qWait(100)
    original = view.snapshot_image()
    assert not original.isNull()
    origin = container.mapToItem(item, QPointF())
    before = (frame.property('capturingPng'), frame.opacity())
    path = tmp_path/'native-whole-tab.png'
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(path), 'PNG'))
    app.exportController.exportScreenshot(center.property('exportItem'), item, dict(scope='tab', anonymous=True))
    wait_until(lambda: not app.exportController.busy, timeout=20000)
    assert not app.exportController.isError, app.exportController.message
    exported = QImage(str(path))
    dpr = window.devicePixelRatio()
    assert exported.width() == pytest.approx(item.width()*dpr, abs=1)
    assert exported.height() == pytest.approx(item.height()*dpr, abs=1)
    bounds = (round(origin.x()*dpr), round(origin.y()*dpr),
              round(container.width()*dpr), round(container.height()*dpr))
    actual = exported.copy(*bounds).convertToFormat(QImage.Format_RGB888)
    expected = original.scaled(actual.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGB888)
    def rgb(image):
        return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(),image.bytesPerLine())[:, :image.width()*3].reshape(image.height(),image.width(),3)
    expected_pixels = rgb(expected)[2:-2,2:-2].astype(float)
    assert expected_pixels.std() > 5, 'Native fixture must contain visible rendered content'
    assert np.abs(rgb(actual)[2:-2,2:-2].astype(float)-expected_pixels).mean() < 2
    assert (frame.property('capturingPng'), frame.opacity()) == before
    assert view.snapshot_image() == original
    assert not exported.textKeys()
    assert not warnings, warnings
    for scope in ('viewport', 'tab'):
        hidden_path = tmp_path / ('native-no-directions-' + scope + '.png')
        monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName',
                            lambda *args: (str(hidden_path), 'PNG'))
        app.exportController.exportScreenshot(center.property('exportItem'), item,
                                              dict(scope=scope, anonymous=True, directions=False))
        wait_until(lambda: not app.exportController.busy, timeout=20000)
        assert not app.exportController.isError, app.exportController.message
        hidden = QImage(str(hidden_path))
        hidden_native = hidden.copy(*bounds) if scope == 'tab' else hidden
        hidden_pixels = rgb(hidden_native.convertToFormat(QImage.Format_RGB888)).astype(float)
        source_pixels = rgb(original.convertToFormat(QImage.Format_RGB888)).astype(float)
        assert hidden_pixels.shape == source_pixels.shape
        height, width = hidden_pixels.shape[:2]
        assert np.abs(hidden_pixels[:height//3, 2*width//3:] - source_pixels[:height//3, 2*width//3:]).mean() > 1
        assert np.abs(hidden_pixels[height//3:2*height//3, width//3:2*width//3] - source_pixels[height//3:2*height//3, width//3:2*width//3]).mean() < 1
        assert view._host.backend.marker.GetEnabled()
        assert view.snapshot_image() == original
        assert (frame.property('capturingPng'), frame.opacity()) == before

    backend = view._host.backend
    render = backend.render
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError('Synthetic capture render failure')
        return render(*args, **kwargs)
    monkeypatch.setattr(backend, 'render', fail_once)
    with pytest.raises(RuntimeError, match='Synthetic capture'):
        view.snapshot_image(directions=False)
    assert backend.marker.GetEnabled()
    assert view.snapshot_image() == original
    backend.marker.SetEnabled(False)
    try:
        hidden_before = view.snapshot_image()
        assert view.snapshot_image(directions=False) == hidden_before
        assert not backend.marker.GetEnabled()
        assert view.snapshot_image() == hidden_before
    finally:
        backend.marker.SetEnabled(True)
        backend.marker.InteractiveOff()
        render(view.state, False, view.display_state, view.visible_mask)
    assert view.snapshot_image() == original
    print('Native screenshot evidence:', path)


def test_integer_fields_accept_qml_whole_numbers_only():
    from voxplane.settings.screenshot_presets import validate_options
    values=validate_options({'longEdge':4096.0,'jpegQuality':90.0})
    assert type(values['longEdge']) is int and values['longEdge']==4096
    assert type(values['jpegQuality']) is int and values['jpegQuality']==90
    for value in [True,4096.5,float('inf'),float('nan'),'4096']:
        with pytest.raises(ValueError):validate_options({'longEdge':value})
