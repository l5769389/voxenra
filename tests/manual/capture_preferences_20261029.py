"""Capture native preferences with isolated demo data. Run with PYTHONPATH=src:tests, Cocoa, and a zh-CN or en-US argument."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlApplicationEngine
from shiboken6 import delete
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_dicom_tags import wait_until
from test_tag_qml import find
from test_corner_transfer import drag_between
from test_settings_redesign import reveal_setting
from PIL import Image
qt=QApplication([])
qt.setQuitOnLastWindowClosed(False)
locale=sys.argv[1]
output=Path('docs/screenshots') / ('en' if locale=='en-US' else '')
output.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(prefix='Voxenra-demo-',dir='/tmp') as temp:
    folder=Path(temp).resolve()
    provider=DicomImageProvider()
    app=AppController(provider,settings_path=folder/'settings.json',pacs_config_path=folder/'pacs.json',pacs_import_root=folder/'imports')
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance','theme','graphite')
    app.workspaceDocumentController.setAutomaticRecovery(False)
    panel=PanelController(favorite_path=folder/'favorites.json')
    paths=[folder/name for name in ('CT examples','MR examples','Reference scans')]
    for path in paths:
        path.mkdir()
        panel.favoriteDirectories.add(str(path))
    dialog=LocalImportDialog(str(paths[0]),favorites=panel.favoriteDirectories)
    dialog.show();dialog.activateWindow();QTest.qWaitForWindowActive(dialog)
    wait_until(lambda:not dialog._loading)
    def shot(widget,name):
        QTest.qWait(180)
        pix=widget.grabWindow() if hasattr(widget,'grabWindow') else widget.grab().toImage()
        pix=pix.scaledToWidth(1280,Qt.SmoothTransformation)
        assert pix.save(str(output/name))
        image=Image.open(output/name);image.save(output/name,optimize=True)
    shot(dialog,'57-directory-favorites-2.1.5.png')
    QTest.mouseClick(dialog.favorite_list.viewport(),Qt.LeftButton,Qt.NoModifier,dialog.favorite_list.visualItemRect(dialog.favorite_list.item(1)).center())
    wait_until(lambda:not dialog._loading and dialog._directory==str(paths[1]))
    dialog.close();delete(dialog)
    engine=QQmlApplicationEngine()
    engine.addImageProvider('dicom',provider);engine.addImageProvider('navigation',SvgIconProvider())
    engine.rootContext().setContextProperty('appController',app)
    engine.load(QUrl.fromLocalFile(str(Path('src/qt_dicom_viewer/qml/Main.qml').resolve())))
    window=engine.rootObjects()[0];window.resize(1280,900);window.show();window.requestActivate();QTest.qWaitForWindowActive(window)
    app.workspaceController.openSettings();app.settingsController.selectCategory('corners')
    source=find(window,'cornerDrag-topLeft-0');reveal_setting(window,source)
    shot(window,'58-corner-editor-2.1.5.png')
    first=Image.open(output/'58-corner-editor-2.1.5.png').convert('RGB')
    field=app.settingsController.values['corners']['topLeft'][0]
    target=find(window,'cornerPreview-bottomRight')
    drag_between(window,source,target)
    assert field in app.settingsController.values['corners']['bottomRight']
    assert field not in app.settingsController.values['corners']['topLeft']
    shot(window,'58-corner-editor-after-2.1.5.png')
    second=Image.open(output/'58-corner-editor-after-2.1.5.png').convert('RGB')
    first.save(output/'58-corner-editor-2.1.5.gif',save_all=True,append_images=[second],duration=[1600,2200],loop=0)
    window.hide();app.shutdown();delete(engine)
print(locale,'capture and state checks passed')
