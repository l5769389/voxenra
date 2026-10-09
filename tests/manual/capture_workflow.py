"""Anonymous real-MR workflow captures; local input stays read-only.

QT_QPA_PLATFORM=cocoa PYTHONPATH=src:tests python tests/manual/capture_workflow.py MR_FOLDER OUTPUT
Use --english for the matching English manual assets. No network services.
"""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import time
import zipfile

import pydicom
from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from test_tag_qml import find, click

ROOT = Path(__file__).resolve().parents[2]
source, output = map(Path, sys.argv[1:3])
output.mkdir(parents=True, exist_ok=True)
english = '--english' in sys.argv
qt = QApplication([])
qt.setQuitOnLastWindowClosed(False)
with TemporaryDirectory(prefix='Voxenra-Demo-', dir='/tmp') as temporary:
    folder = Path(temporary)
    # An anonymous copy is used for the real ZIP import. Never edit source files.
    paths = sorted(p for p in source.rglob('*') if p.is_file())
    archive = folder/'MR-series.zip'
    imported_count = 0
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for n, path in enumerate(paths):
            ds = pydicom.dcmread(path, force=True)
            if 'PixelData' not in ds: continue
            uid = str(ds.SeriesInstanceUID)
            imported_count += 1
            ds.PatientName = 'Demo^MR'; ds.PatientID = 'Anonymous'
            ds.StudyDate = ''; ds.StudyTime = ''; ds.PatientBirthDate = ''
            ds.StudyDescription = 'MR'; ds.SeriesDescription = '3D T1'
            stream = BytesIO(); ds.save_as(stream, enforce_file_format=True)
            target.writestr(f'MR/{n:04}.dcm', stream.getvalue())
    provider = DicomImageProvider()
    app = AppController(provider, settings_path=folder/'settings.json',
                        pacs_config_path=folder/'pacs.json', pacs_import_root=folder/'imports')
    app.workspaceDocumentController.setAutomaticRecovery(False)
    app.languageController.selectLanguage('en-US' if english else 'zh-CN')
    for group, key, value in [('appearance','theme','graphite'), ('layout','rightPanelWidth',300),
                             ('corners','topRight',[]), ('corners','topLeft',['viewPosition','seriesDescription','slice'])]:
        app.settingsController.setValue(group,key,value)
    engine = QQmlApplicationEngine(); engine.addImageProvider('dicom',provider)
    engine.addImageProvider('navigation',SvgIconProvider()); engine.rootContext().setContextProperty('appController',app)
    warnings=[]; engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
    engine.load(QUrl.fromLocalFile(str(ROOT/'src/qt_dicom_viewer/qml/Main.qml')))
    window=engine.rootObjects()[0]; window.resize(1440,900); window.show()
    ws=app.workspaceController; frames=[]
    def pump(ms=160):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: qt.processEvents(); time.sleep(.005)
    def wait(predicate):
        end=time.monotonic()+45
        while not predicate() and time.monotonic()<end: pump(25)
        assert predicate(); pump()
    def shot(name=None, target=None):
        pump(); target=target or window
        if name == '36-workspace-full':
            screen=QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()
            picture=screen.grabWindow(0,window.x(),window.y(),window.width(),window.height())
        else:
            picture=target.grabWindow() if hasattr(target,'grabWindow') else target.grab()
        assert not picture.isNull()
        if name: assert picture.save(str(output/(name+'.png')))
        buffer=QBuffer(); buffer.open(QIODevice.WriteOnly); picture.save(buffer,'PNG')
        frame=Image.open(BytesIO(bytes(buffer.data()))).convert('RGB')
        frame.thumbnail((1100,688),Image.Resampling.LANCZOS); frames.append(frame)
    try:
        shot('42-workspace-home')
        mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(archive))])
        for position in [QPoint(700,300),QPoint(840,380)]:
            event=(QDragEnterEvent if len(frames)==1 else QDragMoveEvent)(position,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(window,event); assert event.isAccepted(); shot('35-zip-drop')
        event=QDropEvent(QPointF(840,380),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(window,event); assert event.isAccepted(); shot()
        wait(lambda:not app.panelController.scanning)
        assert not app.panelController.importError, app.panelController.statusMessage
        records = list(app.panelController._scan_series_record.values())
        assert records, app.panelController.statusMessage
        record = max(records, key=lambda r:len(r.instances))
        assert len(record.instances) == imported_count
        uid = record.series_instance_uid
        app.panelController.openSeriesView(uid,'2d')
        wait(lambda:ws.activeLoadState is not None and ws.activeLoadState.status=='ready')
        view=ws.activeViewport; view.setSliceIndex(view.sliceCount//2)
        wait(lambda:view.loadState=='ready'); view.autoWindow(); shot('37-theme-graphite')
        frames[0].save(output/'06-zip-drag.gif',save_all=True,append_images=frames[1:],duration=[750,650,650,650,2000],loop=0,disposal=2)
        ws.activeTab.toolController.activateTool('export'); shot('18-export')
        click(window,find(window,'sidebarWorkspace')); pump()
        dialog=window.findChild(QObject,'workspaceDocumentDialog')
        wait(lambda:dialog.property('visible'))
        shot('36-workspace-full'); shot('17-workspace',dialog.findChild(QObject,'workspaceDocumentMessage').window())
        dialog.findChild(QObject,'workspaceDocumentMessage').window().close(); pump()
        ws.openSettings()
        for category,name in [('appearance','38-appearance-settings'),('window','39-window-presets'),('input','40-input-settings'),('privacy','41-privacy-settings')]:
            app.settingsController.selectCategory(category); shot(name)
        ws.closeTab('workspace-settings')
        examples=folder/'Import-Examples'; examples.mkdir(); (examples/'MR-series').mkdir()
        (examples/'MR-series.zip').write_bytes(archive.read_bytes())
        with zipfile.ZipFile(archive) as bundle:
            (examples/'single-image.dcm').write_bytes(bundle.read(bundle.namelist()[0]))
        picker=LocalImportDialog(str(examples)); picker.show(); pump(); picker.view.selectAll()
        shot('15-mixed-import',picker); picker.close()
        assert not warnings,warnings
        print('ZIP import, MR, workspace, settings captured; no QML warnings',flush=True)
    finally:
        window.hide(); app.shutdown(); delete(engine)
