import base64
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from voxplane.settings.screenshot_presets import validate_options
from voxplane.ui.controller.screenshot_preview_controller import ScreenshotPreviewController


@pytest.mark.parametrize('format,quality',[('png',90),('jpeg',1),('jpeg',100)])
def test_frozen_encoded_preview_matches_saved_file(qt_app,tmp_path,format,quality):
    preview=ScreenshotPreviewController()
    image=QImage(200,100,QImage.Format_RGB32);image.fill(0xff887766)
    preview.set_image(image,validate_options({'format':format,'jpegQuality':quality}),tmp_path/'image')
    expected=base64.b64decode(preview.source.split(',',1)[1])
    image.fill(0xff000000)
    assert preview.save_to(tmp_path/'saved')
    assert (tmp_path/'saved').read_bytes()==expected
    assert '200 × 100' in preview.dimensions
    preview.clear()
    assert not preview.save_to(tmp_path/'cancelled')
    assert not (tmp_path/'cancelled').exists()


def test_actual_preview_directory_save_and_escape(sidebar_scene,monkeypatch,tmp_path):
    window,app,records,warnings=sidebar_scene
    folder=tmp_path/'chosen';folder.mkdir()
    app.settingsController.setValue('export','directory',str(folder))
    ws=app.workspaceController
    ws.createTab(records[0].series_instance_uid,'Preview','2d')
    wait_until(lambda:ws.activeLoadState.status=='ready')
    click(window,find(window,'primaryTool-export'))
    chosen=[]
    target=folder/'output.png'
    def picker(*args):
        chosen.append(args[2]);return str(target),'PNG'
    monkeypatch.setattr('voxplane.ui.controller.screenshot_preview_controller.QFileDialog.getSaveFileName',picker)
    click(window,find(window,'exportPng'))
    preview=app.exportController.screenshotPreview
    wait_until(lambda:preview.ready)
    assert not chosen and not target.exists()
    image=find(window,'actualScreenshotPreview')
    wait_until(lambda: image.property('ready') and image.width()>0 and image.height()>0)
    QTest.qWait(120)
    assert window.grabWindow().save(str(tmp_path/'actual-preview.png'))
    original=base64.b64decode(preview.source.split(',',1)[1])
    click(window,find(window,'saveScreenshotPreview'))
    assert Path(chosen[0]).parent==folder
    assert target.read_bytes()==original
    assert not preview.ready
    click(window,find(window,'exportPng'));wait_until(lambda:preview.ready)
    QTest.keyClick(window,Qt.Key_Escape)
    wait_until(lambda:not preview.ready)
    assert len(chosen)==1
    assert not warnings,warnings

from pathlib import Path


@pytest.mark.parametrize('flag',['measurements','directions','scale','parameters'])
def test_each_screenshot_layer_switch_changes_actual_pixels(sidebar_scene,flag):
    from voxplane.model import MeasurementKind,ImagePoint
    window,app,records,warnings=sidebar_scene
    ws=app.workspaceController;ws.createTab(records[0].series_instance_uid,'Layers','2d')
    wait_until(lambda:ws.activeLoadState.status=='ready')
    vp=ws.activeViewport
    vp.measurementController.paste_points([ImagePoint(20,30),ImagePoint(60,65)],vp._measurement_context(3,2,kind=MeasurementKind.LENGTH))
    center=find(window,'centerPanel');wait_until(lambda:center.property('exportItem') is not None)
    item=center.property('exportItem');QTest.qWait(60)
    def capture(options):
        app.exportController.previewScreenshot(item,item,dict(anonymous=False,**options))
        wait_until(lambda:app.exportController.screenshotPreview.ready)
        data=base64.b64decode(app.exportController.screenshotPreview.source.split(',',1)[1])
        image=QImage.fromData(data).convertToFormat(QImage.Format_RGB32)
        assert not item.property('capturingPng')
        return bytes(image.constBits())
    assert capture({})!=capture({flag:False})
    assert not warnings,warnings
